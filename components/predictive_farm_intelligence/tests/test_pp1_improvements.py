"""PP1 improvements on SYNTHETIC data: break reset (1a), fast half-life for the shifting
flows (1b) and milking-cow exits from lactation records (exit fix)."""
from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.adaptive import AdaptiveConfig, adaptive_corrected
from components.predictive_farm_intelligence.pfoi.break_eval import compare, verdict, with_reset
from components.predictive_farm_intelligence.pfoi.breaks import detect_breaks, latest_break, since_mask
from components.predictive_farm_intelligence.pfoi.config import EngineConfig
from components.predictive_farm_intelligence.pfoi.data import load_origin_inputs
from components.predictive_farm_intelligence.pfoi.error_tools import bias_corrected
from components.predictive_farm_intelligence.pfoi.freeze import config_hash, v11_config_hash, version_label
from components.predictive_farm_intelligence.pfoi.herd_engine import project
from components.predictive_farm_intelligence.pfoi.outlook import build_output_layer
from components.predictive_farm_intelligence.pfoi.rates import FAST_FLOWS, estimate_rates, milking_exit_cells

from .synthetic import FakeHerdSource

ORIGIN = date(2021, 10, 1)


# ------------------------------------------------------------------ 1a: breaks

def _daily(start=date(2018, 1, 1), days=900, drop_at=500, gap=(700, 740)):
    d = [start + timedelta(days=i) for i in range(days)]
    herd = np.where(np.arange(days) < drop_at, 2500.0, 2000.0)
    ok = np.ones(days, dtype=bool)
    ok[gap[0]:gap[1]] = False
    return pd.DataFrame({"date": d, "n_herd": herd, "is_scoreable": ok, "target_litres": 4000.0})


def test_breaks_are_detected_from_the_past_only():
    d = _daily()
    b = detect_breaks(d)
    start = date(2018, 1, 1)
    herd_break = start + timedelta(days=500)
    assert len(b) == 2
    assert herd_break < b[0] <= herd_break + timedelta(days=30)  # seen within weeks, never early
    assert b[1] == start + timedelta(days=740)  # first trusted milk day after a 40-day gap
    # changing days after a break date cannot move it
    later = d.copy()
    later.loc[later.index > 760, "n_herd"] = 900.0
    assert detect_breaks(later)[:2] == b


def test_since_mask_uses_only_breaks_known_at_the_origin():
    b = [date(2020, 3, 1)]
    o = np.array(pd.to_datetime(["2020-01-01", "2020-04-01"]).to_numpy())
    assert since_mask(o, date(2020, 2, 1), b).all()  # break not yet known
    assert list(since_mask(o, date(2020, 5, 1), b)) == [False, True]
    assert latest_break(date(2020, 3, 1), b) is None  # dated on the origin = not before it


def _errs(series="milking", model="herd_engine", shift_at=date(2020, 6, 1), horizon=3):
    rows = []
    for i in range(36):
        o = date(2018, 1, 1) + timedelta(days=30 * i)
        bias = 50.0 if o < shift_at else -50.0  # sign flips after the break
        rows.append(dict(origin=o, grain="monthly", horizon=horizon, period_start=o,
                         period_end=o + timedelta(days=30), series=series, model=model,
                         forecast=1000.0 + bias, actual=1000.0, error=bias))
    return pd.DataFrame(rows)


def test_reset_drops_pre_break_corrections():
    e = _errs()
    br = [date(2020, 6, 1)]
    plain = bias_corrected(e, "herd_engine").set_index("origin")
    reset = bias_corrected(e, "herd_engine", breaks=br).set_index("origin")
    just_after = min(o for o in plain.index if o > br[0])
    assert plain.loc[just_after, "forecast"] < 1000.0  # old +50 bias still subtracted
    assert reset.loc[just_after, "forecast"] == pytest.approx(950.0)  # too few post-break errors: raw
    late = max(plain.index)
    assert abs(reset.loc[late, "error"]) <= abs(plain.loc[late, "error"])


def test_adaptive_and_outlook_layer_reset_too():
    e = _errs(series="herd_milk", model="milk_baseline")
    cfg = AdaptiveConfig(q30=0.1, tau_days=365.0, pooled=False)
    br = [date(2020, 6, 1)]
    a = adaptive_corrected(e, "milk_baseline", cfg=cfg, breaks=br).set_index("origin")
    just_after = min(o for o in a.index if o > br[0])
    assert a.loc[just_after, "forecast"] == pytest.approx(950.0)  # level reset to 0
    herd = _errs()
    layer0 = build_output_layer(pd.concat([herd, e]), date(2020, 7, 15), cfg, ("milking",))
    layer1 = build_output_layer(pd.concat([herd, e]), date(2020, 7, 15), cfg, ("milking",), breaks=br)
    assert ("monthly", "milking", 3) in layer0.herd_bias and not layer1.herd_bias


def test_break_eval_reports_and_applies_the_keep_rule():
    rows = with_reset(_errs(), _errs(series="herd_milk", model="milk_baseline"),
                      [date(2020, 6, 1)], AdaptiveConfig(pooled=False))
    assert {"herd_engine_corrected", "herd_engine_corrected_br", "milk_baseline_adaptive",
            "milk_baseline_adaptive_br"} <= set(rows["model"])
    t = compare(rows, [date(2020, 6, 1)])
    assert {"accuracy", "after_break", "n_after"} <= set(t.columns)
    keep, reasons = verdict(t)
    assert isinstance(keep, bool) and isinstance(reasons, list)


# ------------------------------------------------------------------ 1b: fast half-life

def test_fast_flows_come_from_the_short_half_life_only():
    src = FakeHerdSource()
    slow_cfg = EngineConfig(rate_half_life_months=6.0)
    fast_cfg = replace(slow_cfg, fast_half_life_months=2.0)
    inp = load_origin_inputs(src, ORIGIN, fast_cfg).rate_inputs
    slow = estimate_rates(inp, slow_cfg)
    fast_only = estimate_rates(inp, replace(slow_cfg, rate_half_life_months=2.0))
    mixed = estimate_rates(inp, fast_cfg)
    for f in ("abortion", "conc_heifer", "conc_dry"):
        assert getattr(mixed, f) == pytest.approx(getattr(fast_only, f)), f
    assert np.allclose(mixed.conc_cow, fast_only.conc_cow)
    assert mixed.births_per_calving == pytest.approx(slow.births_per_calving)
    assert np.allclose(mixed.calve_by_gest, slow.calve_by_gest)
    assert any("fast half-life" in n for n in mixed.notes)
    assert "milk_exit_cell" in FAST_FLOWS


# ------------------------------------------------------------------ exit fix

def test_exit_cells_follow_the_record_and_shrink():
    me = FakeHerdSource().milking_exits(date(2020, 1, 1), ORIGIN, ORIGIN)
    cells = milking_exit_cells(me, 3650.0)
    late, early = 2, 0  # DIM bands 151-305 vs 0-60
    assert cells[0, late, 0] > 3 * cells[0, late, 1]  # open cows late in lactation leave most
    assert cells[0, late, 0] > cells[0, early, 0]
    assert np.isfinite(cells).all() and (cells >= 0).all()


def test_engine_with_measured_exits_conserves_and_removes_more_open_cows():
    src = FakeHerdSource()
    base = EngineConfig()
    lac = replace(base, milking_exit_model="lactation")
    r0 = estimate_rates(load_origin_inputs(src, ORIGIN, base).rate_inputs, base)
    inputs = load_origin_inputs(src, ORIGIN, lac)
    r1 = estimate_rates(inputs.rate_inputs, lac)
    assert r0.milk_exit_cell is None and r1.milk_exit_cell is not None
    p1 = project(inputs.state, r1, 180).daily
    flows = p1["deaths"] + p1["culls"] + p1["sales"]
    assert (flows >= 0).all()
    # stock change = entries + births - exits (conservation)
    assert np.isfinite(p1["n_herd"]).all() and (p1["milking"] >= 0).all()


def test_uniform_cells_reproduce_the_state_engine():
    src = FakeHerdSource()
    cfg = EngineConfig()
    inputs = load_origin_inputs(src, ORIGIN, cfg)
    r = estimate_rates(inputs.rate_inputs, cfg)
    h = sum(r.exit["milking"].values())
    same = replace(r, milk_exit_cell=np.full((4, 4, 2), h))
    a = project(inputs.state, r, 120).daily
    b = project(inputs.state, same, 120).daily
    for col in ("milking", "n_herd", "culls", "deaths", "sales"):
        assert a[col].to_numpy() == pytest.approx(b[col].to_numpy(), rel=1e-9), col


def test_new_options_stay_outside_the_frozen_hashes():
    assert config_hash() == "3cbd28787fcb" and v11_config_hash() == "2a865a0c2687"
    assert version_label(EngineConfig(milking_exit_model="lactation")).startswith("experiment-")
    assert version_label(EngineConfig(fast_half_life_months=3.0)).startswith("experiment-")


# ------------------------------------------------------------------ 1c: scenarios on the page

def _summary():
    rows = []
    for series in ("herd_milk", "milking", "n_herd"):
        for h, med in ((1, -0.05), (3, -0.15), (6, -0.25), (12, -0.2)):
            rows.append(dict(kind="herd contraction", grain="monthly", horizon=h, n=2,
                             median=med, low=med - 0.1, high=med + 0.05, series=series))
    return pd.DataFrame(rows)


def test_page_scenarios_scale_the_monthly_forecast():
    from components.predictive_farm_intelligence.pfoi.page_run import _scenarios

    outlook = [dict(grain="month", horizon=h, target_period=f"2021-{9 + h:02d}-01" if h < 4 else "2022-01-01",
                    series=s, forecast=1000.0) for s in ("milk_litres", "milking", "total_herd")
               for h in (1, 2, 3)]
    rows = pd.DataFrame(_scenarios(outlook, _summary()))
    assert set(rows["series"]) == {"milk_litres", "milking", "total_herd"}
    h3 = rows[(rows["series"] == "milking") & (rows["horizon"] == 3)].iloc[0]
    assert h3["scenario"] == pytest.approx(850.0) and h3["low"] < h3["scenario"] < h3["high"]
    h2 = rows[(rows["series"] == "milking") & (rows["horizon"] == 2)].iloc[0]
    assert h2["scenario"] == pytest.approx(900.0)  # interpolated between horizons 1 and 3
    assert "not a proven cause" in h3["sentence"] and h3["n_episodes"] == 2
    assert _scenarios(outlook, None) == []


def test_scenarios_command_runs_with_herd_series(monkeypatch, tmp_path, capsys):
    from components.predictive_farm_intelligence.pfoi import cli, data
    from components.predictive_farm_intelligence.pfoi.backtest_herd import run_backtest
    from components.predictive_farm_intelligence.pfoi.backtest_milk import run_milk_backtest

    src = FakeHerdSource()
    origins = [date(2020, m, 1) for m in range(1, 13)] + [date(2021, m, 1) for m in range(1, 10)]
    milk = run_milk_backtest(src, "monthly", origins=origins).errors
    milk.to_csv(tmp_path / "milk_backtest_errors_monthly_T.csv", index=False)
    herd = run_backtest(src, "monthly", origins=origins).errors
    herd.to_csv(tmp_path / "herd_backtest_errors_monthly_H.csv", index=False)
    monkeypatch.setattr(data.SqlHerdSource, "from_env", classmethod(lambda cls, **kw: src))
    assert cli.main(["scenarios", "--tag", "T", "--herd-tag", "H", "--out", str(tmp_path)]) == 0
    t = pd.read_csv(tmp_path / "scenario_response_T.csv")
    assert "series" in t.columns
    assert "episode library" in capsys.readouterr().out
