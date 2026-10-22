"""Structural gated TCN tests on fictional synthetic herd aggregates only; no database."""
from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

torch = pytest.importorskip("torch")

from components.predictive_farm_intelligence.pfoi.tcn_specialist import (  # noqa: E402
    CELLS, CELL_INDEX, LOOKBACK, MODEL, SEQ, STATIC, Daily, FoldResult, TCNConfig, build_samples,
    make_net, run_folds, run_tcn_specialist, tcn_rows,
)

START, END = date(2015, 8, 1), date(2020, 1, 1)
FAST = TCNConfig(channels=4, dilations=(1, 2), seeds=(0,), max_epochs=2, patience=1,
                 min_train=20, fold_years=(2019,), batch=32)


def _daily(step_from=None, cow_factor=1.0):
    days = pd.date_range(START, END - timedelta(days=1))
    t = np.arange(len(days))
    milking = np.full(len(days), 400.0)
    herd = np.full(len(days), 900.0)
    if step_from is not None:
        changed = days.date >= step_from
        milking = np.where(changed, milking * cow_factor, milking)
        herd = np.where(changed, herd * cow_factor, herd)
    ypc = 10.0 + 1.2 * np.sin(2 * np.pi * t / 365.25)
    mastitis = np.where(t % 31 == 0, 2.0, 0.0)
    return pd.DataFrame({
        "date": days.date,
        "target_litres": milking * ypc,
        "target_source": np.where(days < "2018-08-01", "shipment", "delpro"),
        "is_scoreable": True,
        "identified_share": 0.85,
        "data_gap": 0,
        "milking": milking,
        "n_herd": herd,
        "exits": np.where(t % 17 == 0, 3.0, 0.0),
        "external_entries": np.where(t % 23 == 0, 2.0, 0.0),
        "calvings": np.where(t % 19 == 0, 2.0, 0.0),
        "real_abortions": np.where(t % 47 == 0, 1.0, 0.0),
        "mastitis_episodes": mastitis,
        "weather_is_complete": True,
        "thi_mean": 70.0 + 4.0 * np.sin(2 * np.pi * t / 365.25),
    })


def _period(origin: pd.Timestamp, grain: str, horizon: int):
    horizon = int(horizon)
    if grain == "weekly":
        start = origin + timedelta(days=7 * (horizon - 1))
        return start, start + timedelta(days=7)
    start = origin + pd.DateOffset(months=horizon - 1)
    return start, start + pd.DateOffset(months=1)


def _base(daily, end_year=2019, every="14D"):
    series = pd.Series(daily["target_litres"].to_numpy(), index=pd.to_datetime(daily["date"]))
    rows = []
    for origin in pd.date_range("2016-01-04", f"{end_year}-11-04", freq=every):
        for grain, horizon in CELLS:
            start, end = _period(origin, grain, horizon)
            target = series.loc[start:end - timedelta(days=1)]
            if len(target) != (end - start).days:
                continue
            actual = float(target.sum())
            rows.append(dict(origin=origin.date(), grain=grain, horizon=horizon,
                             period_start=start.date(), period_end=end.date(), series="herd_milk",
                             model="milk_baseline_adaptive", forecast=actual * 1.10, actual=actual))
    return pd.DataFrame(rows)


def test_windows_use_only_pre_origin_aggregates_and_include_direct_horizon_inputs():
    origin = date(2018, 5, 7)
    base = _base(_daily())
    selected = base[base["origin"] == origin]
    a = build_samples(Daily.from_frame(_daily()), selected, [origin], None)
    changed = _daily(step_from=origin, cow_factor=0.25)
    b = build_samples(Daily.from_frame(changed), selected, [origin], None)
    assert a.seq.shape == (1, LOOKBACK, len(SEQ))
    assert a.stat.shape == (1, len(STATIC))
    np.testing.assert_allclose(a.seq, b.seq)
    np.testing.assert_allclose(a.stat, b.stat)


def test_persistent_herd_drop_has_a_large_shock_score_and_weight():
    changed = _daily(step_from=date(2018, 4, 1), cow_factor=0.25)
    base = _base(changed)
    calm = build_samples(Daily.from_frame(changed), base, [date(2018, 2, 12)], None, FAST)
    shock = build_samples(Daily.from_frame(changed), base, [date(2018, 4, 9)], None, FAST)
    assert calm.shock[0] < 0.05
    assert shock.shock[0] > 0.5
    assert shock.w[0] > calm.w[0]


def test_single_unconfirmed_stock_collapse_is_rejected_as_an_input_anomaly():
    origin = date(2018, 4, 9)
    daily = _daily()
    anomaly_day = origin - timedelta(days=1)
    daily.loc[daily["date"] == anomaly_day, ["milking", "n_herd"]] = [40.0, 90.0]
    base = _base(daily)
    sample = build_samples(Daily.from_frame(daily), base, [origin], None, FAST)
    assert sample.shock[0] < 0.10


def test_network_has_direct_weekly_monthly_outputs_bounded_corrections_and_soft_gate():
    net = make_net(FAST)
    correction, gate = net(torch.randn(3, LOOKBACK, len(SEQ)), torch.randn(3, len(STATIC)))
    assert correction.shape == gate.shape == (3, len(CELLS))
    assert torch.all((gate > 0) & (gate < 1))
    assert float(correction.detach().abs().max()) <= np.log(2.0) + 1e-6


def test_zero_correction_preserves_structural_scaling():
    daily = _daily()
    base = _base(daily)
    origin = sorted(set(base["origin"]))[0]
    one = base[base["origin"] == origin].copy()
    folds = FoldResult({origin: np.zeros(len(CELLS))}, {origin: np.full(len(CELLS), 0.2)}, {origin: 0.0},
                       pd.DataFrame())
    out = tcn_rows(one, folds, FAST, online=False)
    np.testing.assert_allclose(out["forecast"], one.sort_values(["grain", "horizon"])["forecast"])
    half = one.copy()
    half["forecast"] *= 0.5
    out_half = tcn_rows(half, folds, FAST, online=False)
    np.testing.assert_allclose(out_half["forecast"], out["forecast"] * 0.5)


def test_online_adapter_uses_only_completed_earlier_errors():
    origins = [date(2018, 1, 1) + timedelta(days=14 * i) for i in range(7)]
    rows = []
    for origin in origins:
        start = origin
        end = origin + timedelta(days=7)
        rows.append(dict(origin=origin, grain="weekly", horizon=1, period_start=start, period_end=end,
                         series="herd_milk", model="milk_baseline_adaptive", forecast=110.0, actual=100.0))
    base = pd.DataFrame(rows)
    folds = FoldResult({o: np.zeros(len(CELLS)) for o in origins},
                       {o: np.full(len(CELLS), 0.2) for o in origins}, {o: 0.0 for o in origins}, pd.DataFrame())
    a = tcn_rows(base, folds, FAST)
    changed = base.copy()
    changed.loc[changed.index[-1], "actual"] = 1000.0
    b = tcn_rows(changed, folds, FAST)
    np.testing.assert_allclose(a.iloc[:-1]["forecast"], b.iloc[:-1]["forecast"])
    assert a.iloc[-1]["online_adjustment"] < 0


def test_fold_is_reproducible_and_ignores_later_daily_changes_for_earlier_origins():
    daily = _daily()
    base = _base(daily)
    a = run_folds(Daily.from_frame(daily), base, FAST)
    changed = _daily(step_from=date(2019, 6, 1), cow_factor=0.5)
    b = run_folds(Daily.from_frame(changed), base, FAST)
    earlier = [o for o in a.corrections if o < date(2019, 6, 1)]
    assert earlier
    for origin in earlier:
        np.testing.assert_allclose(a.corrections[origin], b.corrections[origin], atol=1e-7)
        np.testing.assert_allclose(a.gates[origin], b.gates[origin], atol=1e-7)


def test_end_to_end_produces_every_available_weekly_and_monthly_cell():
    daily = _daily(step_from=date(2019, 4, 1), cow_factor=0.7)
    base = _base(daily)
    result = run_tcn_specialist(base, daily, cfg=FAST)
    assert len(result.candidate)
    assert set(zip(result.candidate["grain"], result.candidate["horizon"])).issubset(set(CELLS))
    assert result.fits["fold_year"].nunique() == 1
    assert set(result.checks["check"]).issuperset({"shock-origin weighted hit rate rises"})
    assert result.candidate["model"].eq(MODEL).all()
