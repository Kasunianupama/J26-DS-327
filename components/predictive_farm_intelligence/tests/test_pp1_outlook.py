"""M1 in the outlook, M4 staleness-aware ranges and the record status (SYNTHETIC data only)."""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.config import EngineConfig
from components.predictive_farm_intelligence.pfoi.intervals import (
    StalenessScale, aci_interval_next, widen_relative,
)
from components.predictive_farm_intelligence.pfoi.milk_baseline import (
    WITHHELD_NO_TRUSTED_DAYS, MilkConfig,
)
from components.predictive_farm_intelligence.pfoi.outlook import (
    build_outlook, interval_table, run_frozen, run_interval_table, run_model,
)
from components.predictive_farm_intelligence.pfoi.page_run import build_page_run
from components.predictive_farm_intelligence.pfoi.record_status import record_status

from .synthetic import FakeHerdSource
from .test_outage_recovery import GapSource

ORIGIN = date(2021, 10, 1)


def _stale_table():
    rows = []
    for h in (1, 4):
        for band, sd, n in (("[0, 2)", 0.05, 100), ("[29, 91)", 0.10, 40), ("[91, 181)", 0.08, 5),
                            ("[181, 10000)", 0.20, 30)):
            rows.append(dict(grain="weekly", horizon=h, stale_band=band, n=n, sd=sd * h,
                             q05=-sd, q50=0.0, q95=sd))
    return pd.DataFrame(rows)


def _errors(n=30, spread=0.1, model="milk_baseline", series="herd_milk"):
    rows = []
    for i in range(n):
        o = date(2018, 1, 1) + timedelta(days=30 * i)
        rows.append(dict(model=model, grain="monthly", series=series, horizon=1, origin=o,
                         period_start=o, period_end=o + timedelta(days=30), forecast=100.0,
                         actual=100.0 * (1 + spread * (1 if i % 2 else -1))))
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ staleness scale (M4)

def test_staleness_scale_is_measured_monotone_and_falls_back_to_one():
    s = StalenessScale(_stale_table(), source="measured: test")
    assert s.factor("weekly", 1, 1) == pytest.approx(1.0)
    assert s.factor("weekly", 1, 40) == pytest.approx(2.0)
    assert s.factor("weekly", 1, 100) == pytest.approx(2.0)  # n < 12 band: never narrower
    assert s.factor("weekly", 1, 400) == pytest.approx(4.0)
    assert s.factor("weekly", 2, 40) == pytest.approx(2.0)  # nearest measured horizon above
    assert s.factor("monthly", 1, 400) == 1.0  # grain not measured: no widening
    none = StalenessScale.from_csv(None)
    assert none.source == "not measured" and none.factor("weekly", 1, 400) == 1.0


def test_widen_relative_in_log_space():
    assert widen_relative(-0.1, 0.1, 1.0) == pytest.approx((-0.1, 0.1))
    lo, hi = widen_relative(-0.1, 0.1, 2.0)
    assert np.log1p(lo) == pytest.approx(2 * np.log1p(-0.1))
    assert np.log1p(hi) == pytest.approx(2 * np.log1p(0.1))
    assert widen_relative(-0.9, 0.5, 5.0)[0] > -1.0


# ------------------------------------------------------------------ ACI for the next forecast

def test_aci_next_uses_only_finished_errors():
    e = _errors()
    a = aci_interval_next(e, date(2021, 1, 1))
    later = pd.concat([e, _errors(1, 5.0).assign(origin=date(2021, 1, 1),
                                                 period_end=date(2021, 2, 1))], ignore_index=True)
    b = aci_interval_next(later, date(2021, 1, 1))
    assert len(a) == 1 and a.iloc[0]["q_lo"] < 0 < a.iloc[0]["q_hi"]
    assert b.iloc[0]["q_hi"] == pytest.approx(a.iloc[0]["q_hi"])


def test_published_intervals_unchanged_without_options():
    run = run_frozen(FakeHerdSource(), ORIGIN)
    e = _errors()
    assert run_interval_table(e, run).equals(interval_table(e, ORIGIN))


def test_stale_records_widen_milk_ranges_only():
    src = FakeHerdSource()
    e = pd.concat([_errors(), _errors(series="milking", model="herd_engine")], ignore_index=True)
    plain = run_frozen(src, ORIGIN)
    wide = run_frozen(src, ORIGIN)
    table = _stale_table().assign(grain="monthly")
    wide.interval_opts = {"aci": False, "stale_days": 40.0,
                          "scale": StalenessScale(table, "measured: test")}
    a = run_interval_table(e, plain).set_index("series")
    b = run_interval_table(e, wide).set_index("series")
    assert b.loc["herd_milk", "q_hi"] > a.loc["herd_milk", "q_hi"]
    assert b.loc["milking", "q_hi"] == pytest.approx(a.loc["milking", "q_hi"])


# ------------------------------------------------------------------ M1 in the outlook

@pytest.fixture(scope="module")
def withheld_run():
    origin = date(2021, 12, 1)
    src = GapSource(date(2020, 9, 1), origin)  # outage still on at the forecast date
    run = run_model(src, origin, EngineConfig(), MilkConfig(k_mode="anchor_first"))
    return src, run


def test_withheld_milk_keeps_the_herd_forecast(withheld_run):
    src, run = withheld_run
    assert run.milk_withheld == WITHHELD_NO_TRUSTED_DAYS
    outlook, attribution, _ = build_outlook(src, run.origin, None, None, run=run)
    assert "herd_milk" not in set(outlook["series"])
    assert {"milking", "n_herd", "calvings"} <= set(outlook["series"])
    doc = build_page_run(src, run, attribution, {}, None)
    o = pd.DataFrame(doc["outlook"])
    assert "milk_litres" not in set(o["series"]) and "milking" in set(o["series"])
    rs = doc["record_status"]
    assert rs["status"] == "withheld" and rs["reason"] == WITHHELD_NO_TRUSTED_DAYS
    assert rs["reason_text"] and {w["series"] for w in doc["withheld"]} == {"milk_litres"}
    assert doc["interval_method"]["milk"] == "empirical_quantiles"


def test_legacy_mode_still_refuses_without_calibration():
    origin = date(2021, 12, 1)
    with pytest.raises(ValueError):
        run_model(GapSource(date(2020, 9, 1), origin), origin, EngineConfig(), MilkConfig())


# ------------------------------------------------------------------ record status

def _target(days=120, end=ORIGIN):
    d = [end - timedelta(days=i) for i in range(days, 0, -1)]
    return pd.DataFrame(dict(date=d, target_source="delpro", target_litres=4000.0,
                             is_scoreable=True, identified_share=0.8, data_gap=False))


def _panel(cows=400.0, days=120, end=ORIGIN):
    d = [end - timedelta(days=i) for i in range(days, 0, -1)]
    return pd.DataFrame(dict(date=d, milking=cows))


def test_record_status_current_stale_and_implausible():
    rs = record_status(_target(), _panel(), ORIGIN)
    assert rs["status"] == "current" and rs["staleness_days"] == 1 and rs["fresh_days"] == 28
    checks = {c["check"]: c for c in rs["checks"]}
    assert checks["plausibility"]["value"] == pytest.approx(10.0) and checks["plausibility"]["ok"]
    t = _target()
    t.loc[pd.to_datetime(t["date"]).dt.date >= ORIGIN - timedelta(days=10), "is_scoreable"] = False
    assert record_status(t, _panel(), ORIGIN)["status"] == "stale"
    assert record_status(_target(), _panel(cows=150.0), ORIGIN)["status"] == "stale"  # 26.7 L/cow


def test_record_status_ignores_days_after_the_origin():
    t = pd.concat([_target(), _target(days=30, end=ORIGIN + timedelta(days=30))
                   .assign(target_litres=1e9)], ignore_index=True)
    assert record_status(t, _panel(), ORIGIN) == record_status(_target(), _panel(), ORIGIN)


def test_page_document_gets_ranges_for_the_correction_layer_models():
    """The page must use the same errors as the outlook tables, including the adaptive
    milk model's own errors; the backtest files alone do not contain them."""
    from components.predictive_farm_intelligence.pfoi.adaptive import adaptive_corrected
    from components.predictive_farm_intelligence.pfoi.backtest_milk import run_milk_backtest
    from components.predictive_farm_intelligence.pfoi.freeze import V11_ADAPTIVE, V11_CORRECTED_HERD
    from components.predictive_farm_intelligence.pfoi.outlook import build_output_layer

    src = FakeHerdSource()
    mc = MilkConfig(k_mode="anchor_first")
    origins = [date(2019 + i // 12, i % 12 + 1, 1) for i in range(30)]
    dev = run_milk_backtest(src, "monthly", milk_cfg=mc, origins=origins).errors
    errors = pd.concat([dev, adaptive_corrected(dev, "milk_baseline", cfg=V11_ADAPTIVE)], ignore_index=True)
    run = run_model(src, ORIGIN, EngineConfig(), mc)
    run.layer = build_output_layer(errors, ORIGIN, V11_ADAPTIVE, V11_CORRECTED_HERD)
    _, attr, _ = build_outlook(src, ORIGIN, errors, None, run=run)
    backtests = {("milk", "development"): dev}  # as read from the files: no adaptive rows
    month = lambda d: pd.DataFrame(d["outlook"]).query("series == 'milk_litres' and grain == 'month'")  # noqa: E731
    without = month(build_page_run(src, run, attr, backtests, None))
    with_ = month(build_page_run(src, run, attr, backtests, None, interval_errors=errors))
    assert (without["lower"] == without["upper"]).all()  # the bug: no milk range
    assert (with_["lower"] < with_["upper"]).all()


def test_adaptive_ranges_follow_the_m4_keep_rule():
    """Adaptive ranges for herd series and daily/weekly milk; monthly milk keeps quantiles."""
    run = run_frozen(FakeHerdSource(), ORIGIN)
    e = pd.concat([_errors(), _errors(series="milking", model="herd_engine"),
                   _errors().assign(grain="weekly")], ignore_index=True)
    run.interval_opts = {"aci": True, "quality": None, "stale_days": np.nan, "scale": None}
    out = run_interval_table(e, run).set_index(["grain", "series"])
    plain = interval_table(e, ORIGIN).set_index(["grain", "series"])
    adaptive = aci_interval_next(e, ORIGIN).set_index(["grain", "series"])
    assert len(out) == len(plain)  # one row per (model, grain, series, horizon), none duplicated
    for key, source in ((("monthly", "herd_milk"), plain), (("monthly", "milking"), adaptive),
                        (("weekly", "herd_milk"), adaptive)):
        for col in ("q_lo", "q_hi"):
            assert out.loc[key, col] == pytest.approx(source.loc[key, col]), (key, col)
