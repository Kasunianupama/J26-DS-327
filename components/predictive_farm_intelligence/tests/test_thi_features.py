"""M5 (docs/pp1_plan.md): lagged, herd-relative heat features and the oracle switch.

SYNTHETIC daily drivers only. Checks that weather after ``origin - weather_lag_days`` is
never used operationally, that the heat knot comes from earlier days only, that the
oracle features exist only in oracle runs, and that a planted lagged heat effect is learned.
"""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.drivers import (
    WEATHER_LAG_DAYS, DriverConfig, FeatureBuilder, driver_layer,
)

from .test_drivers import _acc, _daily

ORIGIN = date(2021, 6, 7)
S, E = ORIGIN + timedelta(days=21), ORIGIN + timedelta(days=28)
WEATHER = ("thi_28d", "thi_anom_28d", "hours_thi_28d", "thi_max_3d", "thi_7d",
           "hot_run_days", "heat_load_7d", "rain_30d", "rain_90d")


def _row(daily, cfg=DriverConfig()):
    return FeatureBuilder(daily, cfg).row(ORIGIN, S, E)


def test_default_lag_reflects_era5_latency():
    assert WEATHER_LAG_DAYS == 6 and DriverConfig().weather_lag_days == 6


def test_recent_unpublished_weather_is_never_used():
    d = _daily()
    base = _row(d)
    late = d.copy()
    recent = pd.to_datetime(late["date"]).dt.date >= ORIGIN - timedelta(days=WEATHER_LAG_DAYS - 1)
    late.loc[recent, ["thi_mean", "thi_max", "hours_thi_above", "rain_total_mm"]] = 99.0
    changed = _row(late)
    for name in WEATHER:
        assert changed[name] == pytest.approx(base[name], nan_ok=True), name


def test_knot_uses_earlier_days_only():
    d = _daily()
    b = FeatureBuilder(d, DriverConfig())
    day = pd.Timestamp(ORIGIN) - pd.Timedelta(days=6)
    k = b.knot(day)
    hist = d[pd.to_datetime(d["date"]) <= day]["thi_max"]
    assert k == pytest.approx(np.percentile(hist, 75))
    later = d.copy()
    later.loc[pd.to_datetime(later["date"]) > day, "thi_max"] = 200.0
    assert FeatureBuilder(later, DriverConfig()).knot(day) == pytest.approx(k)
    assert FeatureBuilder(d, DriverConfig(thi_knot_pct=90)).knot(day) > k


def test_hot_run_and_heat_load_by_hand():
    days = pd.date_range("2016-01-01", "2021-12-31")
    d = pd.DataFrame(dict(date=days.date, milking=800.0, weather_is_complete=True,
                          thi_mean=70.0, thi_max=70.0, hours_thi_above=0.0, rain_total_mm=1.0,
                          mastitis_episodes=0.0, udder_teat_episodes=0.0, n_sessions=0.0,
                          n_blood_alarms=0.0, n_conductivity_alarms=0.0, identified_share=0.8))
    wday = pd.Timestamp(ORIGIN) - pd.Timedelta(days=6)
    hot = (days > wday - pd.Timedelta(days=4)) & (days <= wday)  # last 4 available days
    d.loc[hot, "thi_max"] = 80.0
    b = FeatureBuilder(d, DriverConfig())
    knot = b.knot(wday)
    assert knot == pytest.approx(70.0)  # 75th percentile of a nearly constant history
    r = b.row(ORIGIN, S, E)
    assert r["hot_run_days"] == 4  # days above the knot, ending at the last available day
    assert r["heat_load_7d"] == pytest.approx(4 * 10.0 / 7)


def test_oracle_features_only_in_oracle_runs():
    d = _daily()
    names = list(FeatureBuilder(d, DriverConfig()).matrix(
        pd.DataFrame(dict(origin=[ORIGIN], period_start=[S], period_end=[E]))).columns)
    assert "thi_target_actual" not in names and "heat_load_target_actual" not in names
    cfg = DriverConfig(oracle=True)
    assert cfg.label().endswith("_oracle") and DriverConfig().label() == "w6p75"
    a = _row(d, cfg)
    hotter = d.copy()
    inside = (pd.to_datetime(hotter["date"]).dt.date >= S) & (pd.to_datetime(hotter["date"]).dt.date < E)
    hotter.loc[inside, ["thi_mean", "thi_max"]] += 10
    b = _row(hotter, cfg)
    assert b["thi_target_actual"] == pytest.approx(a["thi_target_actual"] + 10)
    for name in WEATHER:  # operational features are blind to the target period
        assert b[name] == pytest.approx(a[name], nan_ok=True), name


def test_planted_lagged_heat_effect_is_learned():
    d = _daily(seed=3)
    b = FeatureBuilder(d, DriverConfig())
    rng = np.random.default_rng(5)
    rows = []
    for o in pd.date_range("2016-09-05", "2023-10-30", freq="W-MON"):
        s, e = o.date(), (o + pd.Timedelta(days=7)).date()
        load = b.row(o.date(), s, e)["heat_load_7d"]
        eff = -0.03 * (load if np.isfinite(load) else 0.0)
        rows.append(dict(origin=o.date(), grain="weekly", horizon=1, period_start=s, period_end=e,
                         series="herd_milk", model="milk_baseline", forecast=1000.0,
                         actual=1000.0 * np.exp(eff + rng.normal(0, 0.005))))
    err = pd.DataFrame(rows)
    res = driver_layer(err, d, "milk_baseline", cfg=DriverConfig(groups=("weather",)))
    late = err["origin"] >= date(2019, 1, 1)
    assert _acc(res.errors[late.to_numpy()]) > _acc(err[late])
    last = res.coefficients[res.coefficients["origin"] == res.coefficients["origin"].max()]
    heat = last.set_index("feature").loc[["heat_load_7d", "thi_max_3d", "thi_7d"], "coef"]
    assert heat.sum() < 0


def test_oracle_runs_are_never_development_candidates():
    from components.predictive_farm_intelligence.pfoi.cli import NOT_DEVELOPMENT

    assert "tag_dr_w6p75_oracle".endswith(NOT_DEVELOPMENT)
    assert not "tag_dr_w6p75".endswith(NOT_DEVELOPMENT)
