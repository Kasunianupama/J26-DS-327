"""M6 (docs/pp1_plan.md): herd-level sensor summaries and recent milk in the driver layer.

SYNTHETIC frames shaped like ``data.sensor_daily`` (herd-level counts per day). Alarms are
sensor signals, not diagnoses; missing sensor days stay missing, never zero or healthy."""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.drivers import (
    PROBATION, SHADOW, DriverConfig, FeatureBuilder, driver_layer,
)

from .test_drivers import _acc, _daily

SENSORS_FROM = date(2018, 1, 1)


def _with_sensors(seed=0, start=SENSORS_FROM, persistent=None):
    d = _daily(seed)
    rng = np.random.default_rng(seed + 10)
    days = pd.to_datetime(d["date"]).dt.date
    on = days >= start
    n = len(d)
    cows = np.where(on, 400.0, np.nan)
    pers = persistent if persistent is not None else rng.uniform(0.01, 0.05, n)
    d["sess"] = np.where(on, 800.0, np.nan)
    d["sess_linked"] = np.where(on, 760.0, np.nan)
    d["sess_attach"] = np.where(on, 40.0, np.nan)
    d["sess_low_yield"] = np.where(on, 30.0, np.nan)
    d["litres"] = np.where(on, 4000.0, np.nan)
    d["expected_litres"] = np.where(on, 4200.0, np.nan)
    d["litres_with_expected"] = np.where(on, 4000.0, np.nan)
    d["entry_lag_p50"] = np.where(on, 0.2, np.nan)
    d["cows_milked"] = cows
    d["cows_persistent"] = cows * pers
    d["cows_both"] = cows * 0.01
    d["cows_blood"] = cows * 0.03
    d["cows_cond"] = cows * 0.02
    d["target_litres"] = 4000.0 * (1 + 0.01 * rng.normal(size=n))
    d["is_scoreable"] = True
    return d


SENSOR = ("persistent_alarm_share_7d", "combined_alarm_share_7d", "attach_problem_share_7d",
          "low_yield_share_7d", "yield_vs_expected_7d", "linked_share_28d", "entry_lag_28d")


def test_sensor_features_are_missing_before_the_sensors_start():
    b = FeatureBuilder(_with_sensors(), DriverConfig())
    before = b.row(SENSORS_FROM - timedelta(days=30), SENSORS_FROM, SENSORS_FROM + timedelta(days=7))
    after = b.row(SENSORS_FROM + timedelta(days=60), SENSORS_FROM + timedelta(days=60),
                  SENSORS_FROM + timedelta(days=67))
    assert all(np.isnan(before[f]) for f in SENSOR)
    assert after["linked_share_28d"] == pytest.approx(0.95)
    assert after["yield_vs_expected_7d"] == pytest.approx(4000 / 4200)
    assert after["attach_problem_share_7d"] == pytest.approx(0.05)


def test_sensor_features_are_missing_after_recording_stops():
    d = _with_sensors()
    stop = date(2021, 1, 1)
    gone = pd.to_datetime(d["date"]).dt.date >= stop
    d.loc[gone, ["sess", "cows_milked"]] = np.nan
    d.loc[gone, ["cows_persistent", "sess_attach"]] = 0.0  # zeros without sessions mean nothing
    b = FeatureBuilder(d, DriverConfig())
    late = stop + timedelta(days=200)
    r = b.row(late, late, late + timedelta(days=7))
    assert all(np.isnan(r[f]) for f in SENSOR)


def test_features_never_see_the_origin_or_later():
    d = _with_sensors()
    origin = date(2020, 6, 1)
    base = FeatureBuilder(d, DriverConfig()).row(origin, origin, origin + timedelta(days=7))
    later = d.copy()
    after = pd.to_datetime(later["date"]).dt.date >= origin
    later.loc[after, ["cows_persistent", "sess_attach", "target_litres"]] *= 5
    r = FeatureBuilder(later, DriverConfig()).row(origin, origin, origin + timedelta(days=7))
    for f in SENSOR + ("milk_trend_14d", "milk_cv_14d"):
        assert r[f] == pytest.approx(base[f], nan_ok=True), f


def test_recent_milk_uses_trusted_days_only():
    d = _with_sensors()
    origin = date(2020, 6, 1)
    days = pd.to_datetime(d["date"]).dt.date
    d.loc[days >= origin - timedelta(days=7), "target_litres"] *= 1.1  # last week up 10 %
    r = FeatureBuilder(d, DriverConfig()).row(origin, origin, origin + timedelta(days=7))
    assert r["milk_trend_14d"] == pytest.approx(np.log(1.1), abs=0.01)
    bad = d.copy()
    bad.loc[days >= origin - timedelta(days=7), "is_scoreable"] = False
    r2 = FeatureBuilder(bad, DriverConfig()).row(origin, origin, origin + timedelta(days=7))
    assert np.isnan(r2["milk_trend_14d"])  # an untrusted week is not read as a level change


def test_late_sensors_go_shadow_then_probation():
    d = _with_sensors(start=date(2022, 6, 1))
    rows = []
    for o in pd.date_range("2016-09-05", "2023-10-30", freq="W-MON"):
        s, e = o.date(), (o + pd.Timedelta(days=7)).date()
        rows.append(dict(origin=o.date(), grain="weekly", horizon=1, period_start=s, period_end=e,
                         series="herd_milk", model="milk_baseline", forecast=1000.0, actual=1000.0))
    res = driver_layer(pd.DataFrame(rows), d, "milk_baseline", cfg=DriverConfig(groups=("sensor",)))
    st = res.coefficients[res.coefficients["feature"] == "persistent_alarm_share_7d"]
    assert set(st["status"]) >= {SHADOW, PROBATION}


def test_planted_alarm_effect_is_learned():
    rng = np.random.default_rng(2)
    n = len(pd.date_range(date(2015, 8, 1), date(2023, 12, 31)))
    pers = np.clip(0.03 + 0.02 * np.sin(np.arange(n) / 40.0) + rng.normal(0, 0.003, n), 0, 1)
    d = _with_sensors(persistent=pers)
    b = FeatureBuilder(d, DriverConfig())
    rows = []
    for o in pd.date_range("2018-03-05", "2023-10-30", freq="W-MON"):
        s, e = o.date(), (o + pd.Timedelta(days=7)).date()
        x = b.row(o.date(), s, e)["persistent_alarm_share_7d"]
        rows.append(dict(origin=o.date(), grain="weekly", horizon=1, period_start=s, period_end=e,
                         series="herd_milk", model="milk_baseline", forecast=1000.0,
                         actual=1000.0 * np.exp(-3.0 * (x - 0.03) + rng.normal(0, 0.003))))
    err = pd.DataFrame(rows)
    res = driver_layer(err, d, "milk_baseline", cfg=DriverConfig(groups=("sensor",)))
    late = (err["origin"] >= date(2020, 6, 1)).to_numpy()
    assert _acc(res.errors[late]) > _acc(err[late])
    last = res.coefficients[res.coefficients["origin"] == res.coefficients["origin"].max()]
    assert last.set_index("feature").loc["persistent_alarm_share_7d", "coef"] < 0
