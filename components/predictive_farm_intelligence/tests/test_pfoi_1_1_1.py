"""pfoi-1.1.1: 12 months at every grain, days reconciled top-down to the corrected months
(SYNTHETIC data, no database)."""
from datetime import date, timedelta

import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.freeze import (
    V11_VERSION, V111_VERSION, v11_config_hash, v111_config_hash,
)
from components.predictive_farm_intelligence.pfoi.outlook import (
    PATH_STOCKS, OutputLayer, build_outlook, path_end, path_horizons, period_starts, run_frozen,
)
from components.predictive_farm_intelligence.pfoi.page_run import build_page_run
from components.predictive_farm_intelligence.pfoi.periods import period_bounds

from .synthetic import FakeHerdSource

ORIGIN = date(2021, 10, 1)
HERD = ("milking", "n_herd", "calvings", "dry_offs")


def _layer() -> OutputLayer:
    """A correction layer with clearly non-trivial terms at every monthly horizon kind."""
    herd_bias = {("monthly", "milking", 1): 3.0, ("monthly", "milking", 12): -5.0,
                 ("monthly", "n_herd", 6): 4.0, ("monthly", "calvings", 3): 0.4,
                 ("monthly", "dry_offs", 12): -0.3,
                 ("weekly", "milking", 1): 50.0, ("daily", "milking", 1): 80.0}  # must not be used
    milk_level = {("monthly", 1): 0.05, ("monthly", 6): -0.08, ("monthly", 12): 0.02,
                  ("daily", 1): 0.5, ("weekly", 4): -0.4}  # per-grain terms: ignored when reconciled
    return OutputLayer(herd_bias, milk_level, HERD)


def _run(src=None, reconciled=True, layer=True):
    run = run_frozen(src or FakeHerdSource(), ORIGIN)
    run.layer = _layer() if layer else None
    run.reconciled = reconciled
    return run


@pytest.fixture(scope="module")
def runs():
    src = FakeHerdSource()
    base = run_frozen(src, ORIGIN)
    v110 = run_frozen(src, ORIGIN)
    v110.layer = _layer()
    v111 = run_frozen(src, ORIGIN)
    v111.layer, v111.reconciled = _layer(), True
    return src, base, v110, v111


def _month_value(daily, col, h, stock):
    s, e = period_bounds(ORIGIN, "monthly", h)
    d = pd.to_datetime(daily["date"]).dt.date
    part = daily.loc[(d >= s) & (d < e), col]
    return float(part.mean() if stock else part.sum())


def test_version_and_hash_are_separate():
    assert V111_VERSION == "pfoi-1.1.1" and V111_VERSION != V11_VERSION
    assert v111_config_hash() != v11_config_hash()
    assert v111_config_hash() == "727ca86ee28c"  # docs/freeze.md
    assert v11_config_hash() == "2a865a0c2687"  # 1.1.0 untouched


def test_path_horizons_cover_exactly_twelve_months():
    for origin, n_days in ((date(2021, 10, 1), 365), (date(2023, 10, 1), 366)):  # leap day inside
        h = path_horizons(origin, period_starts(origin))
        assert h["daily"] == tuple(range(1, n_days + 1)) and h["monthly"] == tuple(range(1, 13))
        starts = period_starts(origin)
        last_week = period_bounds(starts["weekly"], "weekly", h["weekly"][-1])
        assert last_week[1] <= path_end(origin)
        assert period_bounds(starts["weekly"], "weekly", h["weekly"][-1] + 1)[1] > path_end(origin)
        assert len(h["weekly"]) in (51, 52)


def test_reconciled_months_equal_the_corrected_1_1_0_months(runs):
    _, _, v110, v111 = runs
    path = v111.path()
    for col in ("herd_milk", "milking", "n_herd", "calvings", "dry_offs", "dry_open"):
        stock = col in PATH_STOCKS
        for h in range(1, 13):
            corrected = v110.output("monthly", col, h, _month_value(v110.daily, col, h, stock))
            assert _month_value(path, col, h, stock) == pytest.approx(corrected, rel=1e-9, abs=1e-9)


def test_days_keep_the_engine_shape_within_a_month(runs):
    _, base, _, v111 = runs
    path, d = v111.path(), pd.to_datetime(base.daily["date"]).dt.date
    s, e = period_bounds(ORIGIN, "monthly", 2)
    raw = base.daily.loc[(d >= s) & (d < e), "herd_milk"].to_numpy()
    rec = path.loc[(pd.to_datetime(path["date"]).dt.date >= s)
                   & (pd.to_datetime(path["date"]).dt.date < e), "herd_milk"].to_numpy()
    ratio = rec / raw
    assert ratio.max() - ratio.min() < 1e-12  # one factor per month
    assert ratio[0] == pytest.approx(0.92)  # month 2 uses the next scored milk horizon (6: -0.08)


def test_without_layer_the_path_is_the_structural_forecast():
    run = _run(layer=False)
    path = run.path()
    d = pd.to_datetime(run.daily["date"]).dt.date
    keep = (d >= ORIGIN) & (d < path_end(ORIGIN))
    pd.testing.assert_frame_equal(path[["herd_milk", "milking"]].reset_index(drop=True),
                                  run.daily.loc[keep, ["herd_milk", "milking"]].reset_index(drop=True))


def test_zero_structural_month_gets_the_correction_spread_evenly():
    run = _run()
    run.daily = run.daily.copy()
    run.daily["dry_offs"] = 0.0
    run.layer = OutputLayer({("monthly", "dry_offs", 12): -3.1}, {}, HERD)
    path = run.path()
    s, e = period_bounds(ORIGIN, "monthly", 1)
    d = pd.to_datetime(path["date"]).dt.date
    part = path.loc[(d >= s) & (d < e), "dry_offs"]
    assert part.sum() == pytest.approx(3.1) and part.max() - part.min() < 1e-12


def test_outlook_tables_add_up_across_grains(runs):
    src, _, _, v111 = runs
    outlook, _, _ = build_outlook(src, ORIGIN, None, "core-test", run=v111)
    n = outlook.groupby(["grain", "series"]).size()
    assert n.loc[("daily", "herd_milk")] == 365 and n.loc[("daily", "milking")] == 365
    assert n.loc[("monthly", "calvings")] == 12 and n.loc[("weekly", "n_herd")] in (51, 52)
    for series, stock in (("herd_milk", False), ("calvings", False), ("milking", True)):
        day = outlook[(outlook["grain"] == "daily") & (outlook["series"] == series)].copy()
        day["month"] = [pd.Timestamp(p).date().replace(day=1) for p in day["target_period"]]
        agg = day.groupby("month")["forecast"].agg("mean" if stock else "sum")
        mon = outlook[(outlook["grain"] == "monthly") & (outlook["series"] == series)]
        mon = pd.Series(mon["forecast"].to_numpy(), index=[pd.Timestamp(p).date() for p in mon["target_period"]])
        assert (agg - mon.reindex(agg.index)).abs().max() < 1e-6 * max(1.0, mon.abs().max())
        week = outlook[(outlook["grain"] == "weekly") & (outlook["series"] == series)]
        days = pd.Series(day["forecast"].to_numpy(), index=[pd.Timestamp(p).date() for p in day["target_period"]])
        for r in week.itertuples(index=False):
            s = pd.Timestamp(r.target_period).date()
            vals = days.loc[[s + timedelta(days=i) for i in range(7)]]
            assert r.forecast == pytest.approx(vals.mean() if stock else vals.sum(), rel=1e-9, abs=1e-9)


def test_1_1_0_output_is_unchanged(runs):
    """The 1.1.0 publication keeps its horizons and values; 1.1.1 months equal its months."""
    src, _, v110, v111 = runs
    o110, _, _ = build_outlook(src, ORIGIN, None, "core-test", run=v110)
    o111, _, _ = build_outlook(src, ORIGIN, None, "core-test", run=v111)
    n = o110.groupby(["grain", "series"]).size()
    assert n.loc[("daily", "herd_milk")] == 14 and n.loc[("weekly", "herd_milk")] == 13
    key = ["target_period", "series"]
    m110 = o110[o110["grain"] == "monthly"].set_index(key)["forecast"]
    m111 = o111[o111["grain"] == "monthly"].set_index(key)["forecast"]
    pd.testing.assert_series_equal(m110.sort_index(), m111.sort_index(), rtol=1e-9)


def test_page_document_has_every_series_daily_for_twelve_months(runs):
    src, _, _, v111 = runs
    _, attribution, _ = build_outlook(src, ORIGIN, None, "core-test", run=v111)
    doc = build_page_run(src, v111, attribution, {}, "core-test")
    o = pd.DataFrame(doc["outlook"])
    day = o[o["grain"] == "day"]
    assert {"milk_litres", "milking", "total_herd", "calvings", "mastitis_episodes"} <= set(day["series"])
    assert day.groupby("series").size().eq(365).all()
    assert day["target_period"].max() == (path_end(ORIGIN) - timedelta(days=1)).isoformat()
    assert o[o["grain"] == "week"]["horizon"].max() in (51, 52)
    # no reconciled errors given -> no daily range, flagged limited (never a borrowed range);
    # mastitis keeps its rate-based range (recent vs reference rate)
    modelled = day[day["series"] != "mastitis_episodes"]
    assert (modelled["quality_flag"] == "limited").all() and (modelled["lower"] == modelled["upper"]).all()
    mv = pd.DataFrame(doc["moves"])
    assert set(mv[mv["forecast"]]["grain"]) == {"day", "week", "month"}
    a = pd.DataFrame(doc["attribution"])
    assert "day" in set(a[a["series"] == "calvings"]["grain"])
    import json
    json.dumps(doc)


def test_daily_ranges_come_from_reconciled_errors_only(runs):
    src, _, _, v111 = runs
    rows = []
    for i in range(14):
        o = date(2019, 1, 1) + timedelta(days=31 * i)
        for h in (1, 7, 14, 30, 61, 91, 182, 273, 365):
            rows.append(dict(origin=o, grain="daily", horizon=h, period_start=o, period_end=o + timedelta(days=h),
                             series="milk_litres", model="pfoi_reconciled", forecast=100.0,
                             actual=100.0 * (1.2 if i % 2 else 0.8), error=0.0))
    path_err = pd.DataFrame(rows)
    _, attribution, _ = build_outlook(src, ORIGIN, path_err, "core-test", run=v111)
    doc = build_page_run(src, v111, attribution, {("path", "development"): path_err}, "core-test")
    o = pd.DataFrame(doc["outlook"])
    milk = o[(o["grain"] == "day") & (o["series"] == "milk_litres")]
    assert (milk["upper"] > milk["forecast"]).all() and (milk["lower"] < milk["forecast"]).all()
    herd = o[(o["grain"] == "day") & (o["series"] == "milking")]
    assert (herd["lower"] == herd["upper"]).all()  # no reconciled herd errors -> no range
    b = pd.DataFrame(doc["backtest"])
    assert set(b[(b["grain"] == "day")]["horizon"]) == {1, 7, 14, 30, 61, 91, 182, 273, 365}


def test_path_backtest_scores_without_leakage():
    from components.predictive_farm_intelligence.pfoi.backtest_milk import run_milk_backtest
    from components.predictive_farm_intelligence.pfoi.freeze import FROZEN_ENGINE, FROZEN_MILK, V11_ADAPTIVE
    from components.predictive_farm_intelligence.pfoi.path_backtest import (
        PATH_HORIZONS, run_path_backtest, summarise_path,
    )

    origins = [date(2021, 1, 1), date(2021, 4, 1)]
    until = date(2022, 6, 1)

    def run(src):
        layer_errors = run_milk_backtest(src, "monthly", origins=[date(2020, m, 1) for m in range(1, 13)]).errors
        return run_path_backtest(src, origins, layer_errors, FROZEN_ENGINE, FROZEN_MILK, V11_ADAPTIVE, HERD,
                                 score_until=until)

    e = run(FakeHerdSource())
    assert set(e["model"]) == {"pfoi_reconciled", "pfoi_structural"}
    assert (pd.to_datetime(e["period_end"]).dt.date <= until).all()
    for g, hs in PATH_HORIZONS.items():
        assert set(e[e["grain"] == g]["horizon"]) <= set(hs)
    assert {"milk_litres", "milking", "total_herd", "calvings"} <= set(e["series"])
    assert len(summarise_path(e))
    # tripling everything after the first origin moves actuals, never the first origin's forecasts
    f = run(FakeHerdSource(cutoff=origins[0], future_scale=3.0))
    k = ["origin", "grain", "horizon", "series", "model"]
    a, b = e[e["origin"] == origins[0]].set_index(k), f[f["origin"] == origins[0]].set_index(k)
    pd.testing.assert_series_equal(a["forecast"], b["forecast"].reindex(a.index))
    assert (b["actual"].reindex(a.index) > a["actual"]).any()


def test_compare_runs_scores_the_daily_path(tmp_path):
    """compare-runs at day grain: 1.1.0 forecasts 14 days, 1.1.1 a year; both scored on the
    recorded days both forecast; the chart is drawn."""
    from components.predictive_farm_intelligence.pfoi.compare_runs import plot, score

    days = [(date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(30)]

    def doc(n, f):
        return {"outlook": [{"grain": "day", "series": "milking", "target_period": d, "horizon": i + 1,
                             "forecast": f, "lower": f - 5, "upper": f + 5} for i, d in enumerate(days[:n])],
                "realised": [{"grain": "day", "series": "milking", "period": d, "value": 100.0,
                              "scoreable": True} for d in days],
                "actuals": [{"grain": "day", "series": "milking", "period": "2023-12-31", "value": 101.0,
                             "scoreable": True}]}

    v110, v111 = doc(14, 110.0), doc(30, 102.0)
    t = score(v110, v111, series=("milking",), grain="day").iloc[0]
    assert t["n_months"] == 14
    assert t["mae_frozen"] == pytest.approx(10.0) and t["mae_candidate"] == pytest.approx(2.0)
    assert t["cover90_candidate"] == 1.0 and t["cover90_frozen"] == 0.0
    assert score(v110, v111, series=("milking",)).iloc[0]["n_months"] == 0  # no monthly rows
    plot(v110, v111, date(2024, 1, 1), tmp_path / "d.png", series=("milking",), grain="day")
    assert (tmp_path / "d.png").stat().st_size > 0
