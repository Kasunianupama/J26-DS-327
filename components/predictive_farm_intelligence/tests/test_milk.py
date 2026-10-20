"""Milk model on SYNTHETIC data: curves, k, engine litres, benchmarks, intervals, backtest."""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.backtest_milk import (
    BASELINE, CORRECTED, run_milk_backtest, summarise_milk,
)
from components.predictive_farm_intelligence.pfoi.benchmarks import (
    ets_forecast, last_run, sarima_forecast,
)
from components.predictive_farm_intelligence.pfoi.data import LeakageError
from components.predictive_farm_intelligence.pfoi.error_tools import add_intervals
from components.predictive_farm_intelligence.pfoi.herd_engine import (
    N_GEST, MilkCurveArrays, OriginState,
)
from components.predictive_farm_intelligence.pfoi.lactation_curve import (
    PUBLISHED_B, PUBLISHED_C_PER_DAY, fit_curve, fit_herd_shape, fit_wood_wls, published_curve, wood,
)
from components.predictive_farm_intelligence.pfoi.milk_baseline import (
    MilkConfig, MilkHistory, calibration_window, fit_k, prepare_milk,
)

from .synthetic import TRUE_WOOD, FakeHerdSource, wood_true


def _hist(src, end=date(2024, 1, 1)):
    return MilkHistory(cowdays=src.milking_cowdays(date(2015, 8, 1), end),
                       target=src.target_daily(date(2015, 8, 1), end))


def test_wood_wls_recovers_parameters():
    d = np.arange(1, 400)
    a, b, c = fit_wood_wls(d, wood_true(d), np.ones_like(d))
    assert (a, b, c) == pytest.approx(TRUE_WOOD, rel=1e-6)


def test_fit_curve_per_parity_with_pregnancy_factor():
    stats = FakeHerdSource().cow_curve_stats(date(2020, 8, 1), date(2022, 1, 1)).drop(columns="max_date")
    curve = fit_curve(stats)
    a1, b1, c1 = curve.params[0]
    a2, _, _ = curve.params[1]
    assert (b1, c1) == pytest.approx(TRUE_WOOD[1:], rel=1e-3)
    assert a2 / a1 == pytest.approx(1.1, rel=1e-3)
    assert curve.preg_factor[150] == pytest.approx(0.95, rel=1e-3)
    assert curve.preg_factor[200] == pytest.approx(0.90, rel=1e-3)
    assert curve.params[3] == pytest.approx(curve.params[3])  # unknown parity gets a curve


def test_too_little_data_gives_no_fit():
    stats = FakeHerdSource().cow_curve_stats(date(2020, 8, 1), date(2022, 1, 1)).head(50)
    assert fit_curve(stats.drop(columns="max_date")) is None


def test_published_curve_is_mandal_shape():
    c = published_curve()
    assert c.params[0][1:] == (PUBLISHED_B, PUBLISHED_C_PER_DAY)
    assert 40 <= PUBLISHED_B / PUBLISHED_C_PER_DAY <= 50  # peak about day 44


def test_herd_fitted_shape_recovers_true_shape():
    src = FakeHerdSource()
    cd = src.milking_cowdays(date(2016, 1, 1), date(2018, 1, 1))
    agg = cd.groupby(["month", "dim_bin"], as_index=False)["cow_days"].sum()
    target = (agg.assign(l=agg["cow_days"] * wood_true(agg["dim_bin"] + 5))
              .groupby("month")["l"].sum())
    curve = fit_herd_shape(agg, target)
    b, c = curve.params[0][1:]
    assert abs(b - TRUE_WOOD[1]) <= 0.026 and abs(c - TRUE_WOOD[2]) <= 0.0006


def test_engine_curve_litres_match_hand_calculation():
    y = np.zeros((4, 5, 1000))
    y[0, 0, :] = np.arange(1000) * 0.01
    mult = np.ones(N_GEST)
    mult[150:] = 0.5
    arrays = MilkCurveArrays.from_yield(y, mult)
    s = OriginState(origin=date(2021, 1, 1))
    s.milk_open[0, 0, 50] = 2.0  # 2 cows at DIM 50 -> 2 * 0.50
    s.milk_preg[0, 0, 5, 160] = 1.0  # DIM 5*10+5+160 = 215 -> 2.15, halved by pregnancy
    assert arrays.litres(s) == pytest.approx(2 * 0.50 + 1 * 2.15 * 0.5)


def test_calibration_window_ends_two_months_before_origin_month():
    assert calibration_window(date(2021, 6, 15)) == (date(2020, 4, 1), date(2021, 4, 1))


def test_fit_k_per_source():
    months = [date(2019, m, 1) for m in range(1, 13)]
    curve_m = pd.Series(100.0, index=months)
    tm = pd.DataFrame({"litres": 90.0, "share": 1.0, "source": "shipment"}, index=months)
    tm.loc[months[0], ["litres", "share"]] = [45.0, 0.5]  # half the days scoreable
    assert fit_k(curve_m, tm)["shipment"][0] == pytest.approx(0.9)


def test_prepare_milk_recovers_k_with_the_true_shape():
    src = FakeHerdSource()
    origin = date(2021, 10, 1)
    setup = prepare_milk(src, origin, MilkConfig(), _hist(src))
    assert setup.curve.source == "fitted" and setup.k_source == "delpro"
    # The synthetic target uses the base curve for every parity, while the fitted curve has
    # parity levels 1, 1.1, 1.15, so k = 1.05 x sum(base) / sum(parity-scaled).
    start, end = calibration_window(origin)
    cd = src.milking_cowdays(start, end)
    base = cd["cow_days"] * wood_true(cd["dim_bin"] + 5)
    scale = cd["parity_group"].map({"1": 1.0, "2": 1.1, "3+": 1.15})
    expected = 1.05 * base.sum() / (base * scale).sum()
    assert setup.k == pytest.approx(expected, rel=1e-3)
    early = prepare_milk(src, date(2019, 6, 1), MilkConfig(curve_mode="published"), _hist(src))
    assert early.curve.source == "published" and early.k_source == "shipment"
    assert MilkConfig().curve_mode == "herd_fitted"  # development decision
    herd = prepare_milk(src, date(2019, 6, 1), MilkConfig(curve_mode="herd_fitted"), _hist(src))
    assert herd.curve.source == "herd_fitted"


def test_milk_inputs_never_reach_the_origin():
    src = FakeHerdSource()
    origin = date(2021, 10, 1)
    prepare_milk(src, origin, MilkConfig(), _hist(src))
    for name, *args in src.calls:
        if name == "cow_curve_stats":
            assert args[1] <= origin
    bad = FakeHerdSource(leak="cow_curve_stats")
    with pytest.raises(LeakageError):
        prepare_milk(bad, origin, MilkConfig(), _hist(bad))
    with pytest.raises(LeakageError):
        _hist(src).cowdays_before(date(2022, 1, 1), date(2021, 6, 1))  # rows dated after origin


def test_fitted_everywhere_is_flagged():
    src = FakeHerdSource()
    setup = prepare_milk(src, date(2019, 6, 1), MilkConfig(curve_mode="fitted_everywhere"), _hist(src))
    assert setup.curve.uses_later_information and "uses_later_information" in setup.flags


def test_benchmarks_run_and_respect_gaps():
    idx = pd.period_range("2015-01", periods=48, freq="M")
    y = pd.Series(100 + 10 * np.sin(np.arange(48) * 2 * np.pi / 12), index=idx)
    assert np.isfinite(ets_forecast(y, 12, 12)).all()
    assert np.isfinite(sarima_forecast(y, 12, 12)).all()
    y.iloc[40] = np.nan
    assert len(last_run(y)) == 7
    assert sarima_forecast(y, 6, 12) is None  # too short after the gap


def test_intervals_use_only_finished_past_errors():
    rows = []
    for i in range(30):
        o = date(2017, 1, 1) + timedelta(days=30 * i)
        rows.append((o, "monthly", 1, o + timedelta(days=30), "herd_milk", "m", 100.0,
                     100.0 + (10 if i % 2 else -10)))
    e = pd.DataFrame(rows, columns=["origin", "grain", "horizon", "period_end", "series", "model",
                                    "forecast", "actual"])
    out = add_intervals(e).sort_values("origin")
    assert out["lower"].iloc[:12].isna().all()  # fewer than 12 finished past errors
    assert out["lower"].iloc[13] == pytest.approx(90.0) and out["upper"].iloc[13] == pytest.approx(110.0)
    assert out["covered"].dropna().eq(1.0).all()


def test_milk_backtest_monthly_and_weekly():
    src = FakeHerdSource()
    # 2018-03 would score May 2018 (a synthetic gap) at horizon 3; SARIMA needs 36 unbroken
    # months after that gap, so it appears from mid-2021 origins.
    res = run_milk_backtest(src, "monthly", origins=[date(2018, 3, 1), date(2021, 7, 1), date(2021, 8, 1)])
    e = res.errors
    assert {BASELINE, CORRECTED, "persistence", "seasonal_naive", "ets", "sarima"} <= set(e["model"])
    assert not ((pd.to_datetime(e["period_start"]).dt.month == 5)
                & (pd.to_datetime(e["period_start"]).dt.year == 2018)).any()  # gap never scored
    assert (pd.to_datetime(e["period_end"]).dt.date <= date(2024, 1, 1)).all()
    s = summarise_milk(e)
    assert {"mae", "rmse", "bias", "mape_pct", "coverage_pct"} <= set(s.columns)
    w = run_milk_backtest(src, "weekly", origins=[date(2019, 1, 7), date(2021, 3, 1)])
    assert set(w.errors["grain"]) == {"weekly", "daily"}
    assert set(w.errors[w.errors["grain"] == "daily"]["horizon"]) == {1, 7, 14}
    assert "source_switch" not in ";".join(w.errors["flags"].astype(str))


def test_backtest_refuses_test_block():
    with pytest.raises(ValueError):
        run_milk_backtest(FakeHerdSource(), "monthly", origins=[date(2024, 2, 1)])


def test_anchored_k_uses_recent_days_and_starting_herd():
    from components.predictive_farm_intelligence.pfoi.milk_baseline import anchor_k
    from components.predictive_farm_intelligence.pfoi.config import EngineConfig
    from components.predictive_farm_intelligence.pfoi.data import load_origin_inputs

    src = FakeHerdSource()
    origin = date(2021, 10, 4)
    hist = _hist(src)
    setup = prepare_milk(src, origin, MilkConfig(), hist)
    state = load_origin_inputs(src, origin, EngineConfig()).state
    th = hist.target_before(origin)
    anchor_k(setup, th, state, MilkConfig())
    recent = th[pd.to_datetime(th["date"]).dt.date < origin].tail(14)["target_litres"].mean()
    assert setup.k == pytest.approx(recent / setup.arrays.litres(state))
    assert setup.k_source == "anchored:delpro" and "k_window" not in setup.flags
    # window mode leaves k alone
    w = prepare_milk(src, origin, MilkConfig(k_mode="window"), hist)
    k0 = w.k
    anchor_k(w, th, state, MilkConfig(k_mode="window"))
    assert w.k == k0
    # a gap in the last 4 weeks: fall back to the 12-month k and flag it
    gap = th.copy()
    gap.loc[pd.to_datetime(gap["date"]).dt.date >= origin - timedelta(days=28), "is_scoreable"] = False
    g = prepare_milk(src, origin, MilkConfig(), hist)
    kg = g.k
    anchor_k(g, gap, state, MilkConfig())
    assert g.k == kg and "k_window" in g.flags


# ------------------------------------------------- batched snapshots and --jobs

from components.predictive_farm_intelligence.pfoi.config import EngineConfig  # noqa: E402
from components.predictive_farm_intelligence.pfoi.data import (  # noqa: E402
    SnapshotSource, frames_match, prefetch_snapshots, snapshot_dates,
)


class BatchFakeSource(FakeHerdSource):
    """Synthetic source with a ``snapshots_batch`` built from the per-origin methods."""

    def snapshots_batch(self, asofs, known_untils, lag_days):
        self.calls.append(("snapshots_batch", len(asofs)))
        out = {}
        for name in ("cells_on", "milking_clock", "dry_clock", "heifer_clock", "calf_sex_on"):
            parts = []
            for a, k in zip(asofs, known_untils):
                args = {"cells_on": (a,), "calf_sex_on": (a,),
                        "heifer_clock": (a, k, lag_days)}.get(name, (a, k))
                parts.append(getattr(FakeHerdSource, name)(self, *args).assign(asof=a))
            out[name] = pd.concat(parts, ignore_index=True)
        return out


_ORIGINS = [date(2021, 7, 1), date(2021, 8, 1), date(2021, 9, 1)]


def test_prefetch_serves_same_snapshots_as_per_origin_calls():
    src = BatchFakeSource()
    cfg = EngineConfig()
    snaps = prefetch_snapshots(src, _ORIGINS, cfg, chunk=2)
    wrapped = SnapshotSource(src, snaps)
    for o in _ORIGINS:
        asof, ku = snapshot_dates(o, cfg)
        assert frames_match(wrapped.cells_on(asof), src.cells_on(asof))
        assert frames_match(wrapped.milking_clock(asof, ku), src.milking_clock(asof, ku))
        assert frames_match(wrapped.heifer_clock(asof, ku, cfg.pregnancy_check_lag_days),
                            src.heifer_clock(asof, ku, cfg.pregnancy_check_lag_days))
    assert prefetch_snapshots(FakeHerdSource(), _ORIGINS, cfg) == {}  # no batch method


def test_frames_match_ignores_row_order_only():
    a = pd.DataFrame({"g": ["x", "y"], "n": [1.0, 2.0]})
    assert frames_match(a, a.iloc[::-1].reset_index(drop=True))
    assert not frames_match(a, a.assign(n=[1.0, 2.5]))


def test_batched_and_parallel_backtests_match_serial():
    base = run_milk_backtest(FakeHerdSource(), "monthly", origins=_ORIGINS).errors
    batched = run_milk_backtest(BatchFakeSource(), "monthly", origins=_ORIGINS).errors
    par = run_milk_backtest(BatchFakeSource(), "monthly", origins=_ORIGINS,
                            jobs=2, source_factory=BatchFakeSource).errors
    assert len(base) > 0
    pd.testing.assert_frame_equal(base, batched)
    pd.testing.assert_frame_equal(base, par)


def test_jobs_needs_a_source_factory():
    with pytest.raises(ValueError):
        run_milk_backtest(FakeHerdSource(), "monthly", origins=_ORIGINS, jobs=2)


def test_common_periods_keeps_only_shared_forecasts():
    from components.predictive_farm_intelligence.pfoi.backtest_milk import common_periods
    rows = [("monthly", 1, date(2019, 1, 1), date(2019, 1, 1), m, 1.0)
            for m in ("milk_baseline", "persistence", "sarima")]
    rows += [("monthly", 1, date(2019, 2, 1), date(2019, 2, 1), m, 1.0)
             for m in ("milk_baseline", "persistence")]  # no SARIMA for this origin
    e = pd.DataFrame(rows, columns=["grain", "horizon", "origin", "period_start", "model", "error"])
    assert len(common_periods(e)) == 3
    assert len(common_periods(e, ["milk_baseline", "persistence"])) == 4
