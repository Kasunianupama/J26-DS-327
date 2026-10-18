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
    early = prepare_milk(src, date(2019, 6, 1), MilkConfig(), _hist(src))
    assert early.curve.source == "published" and early.k_source == "shipment"
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
