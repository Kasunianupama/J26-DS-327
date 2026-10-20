"""Layer 2 driver layer on SYNTHETIC daily drivers and error tables."""
from datetime import date

import numpy as np
import pandas as pd

from components.predictive_farm_intelligence.pfoi.drivers import (
    ACTIVE, PROBATION, SHADOW, DriverConfig, FeatureBuilder, driver_layer,
)

START, END = date(2015, 8, 1), date(2024, 1, 1)


def _daily(seed=0, sensors_from=date(2021, 6, 1), mastitis_until=date(2020, 1, 1)):
    rng = np.random.default_rng(seed)
    days = pd.date_range(START, END - pd.Timedelta(days=1))
    doy = days.dayofyear.to_numpy()
    thi = 72 + 6 * np.sin(2 * np.pi * (doy - 100) / 365.25) + rng.normal(0, 3, len(days))
    # a few hot spells well above the seasonal norm
    for s in ("2017-04-01", "2019-03-15", "2021-05-01", "2022-04-10"):
        m = (days >= s) & (days < pd.Timestamp(s) + pd.Timedelta(days=45))
        thi[m] += 8
    sessions = np.where(days.date >= sensors_from, 2000.0, 0.0)
    mast = np.where(days.date < mastitis_until, rng.poisson(1.0, len(days)), 0).astype(float)
    return pd.DataFrame(dict(
        date=days.date, milking=800.0, weather_is_complete=True, thi_mean=thi,
        thi_max=thi + 5, hours_thi_above=np.clip(thi - 72, 0, None), rain_total_mm=rng.gamma(1, 4, len(days)),
        mastitis_episodes=mast, udder_teat_episodes=0.0, n_sessions=sessions,
        n_blood_alarms=np.where(sessions > 0, rng.poisson(30, len(days)), 0).astype(float),
        n_conductivity_alarms=np.where(sessions > 0, rng.poisson(20, len(days)), 0).astype(float),
        identified_share=0.8,
    ))


def _errors(daily, heat_effect=-0.02, seed=1):
    """Weekly origins, 4 weeks ahead; actual falls with the heat of the 28 days before."""
    rng = np.random.default_rng(seed)
    b = FeatureBuilder(daily, DriverConfig())
    rows = []
    for o in pd.date_range("2016-09-05", "2023-10-30", freq="W-MON"):
        s = (o + pd.Timedelta(days=21)).date()
        e = (o + pd.Timedelta(days=28)).date()
        anom = b.row(o.date(), s, e)["thi_anom_28d"]
        eff = heat_effect * (anom if np.isfinite(anom) else 0.0)
        rows.append(dict(origin=o.date(), grain="weekly", horizon=4, period_start=s, period_end=e,
                         series="herd_milk", model="milk_baseline", forecast=1000.0,
                         actual=1000.0 * np.exp(eff + rng.normal(0, 0.01))))
    return pd.DataFrame(rows)


def _acc(d):
    return 1 - (d["forecast"] - d["actual"]).abs().sum() / d["actual"].sum()


def test_features_use_only_days_before_the_origin():
    d = _daily()
    origin = date(2020, 6, 1)
    a = FeatureBuilder(d).row(origin, date(2020, 6, 22), date(2020, 6, 29))
    d2 = d.copy()
    late = pd.to_datetime(d2["date"]).dt.date >= origin
    d2.loc[late, ["thi_mean", "rain_total_mm", "mastitis_episodes"]] *= 10
    b = FeatureBuilder(d2).row(origin, date(2020, 6, 22), date(2020, 6, 29))
    assert all((np.isnan(a[k]) and np.isnan(b[k])) or a[k] == b[k] for k in a)


def test_later_outcomes_do_not_change_the_adjustment_at_an_origin():
    d = _daily()
    e = _errors(d)
    origin = date(2021, 3, 1)
    r1 = driver_layer(e, d, "milk_baseline").errors
    e2 = e.copy()
    e2.loc[pd.to_datetime(e2["period_end"]).dt.date > origin, "actual"] *= 2
    r2 = driver_layer(e2, d, "milk_baseline").errors
    f = lambda r: float(r.loc[r["origin"] == origin, "forecast"].iloc[0])
    assert f(r1) == f(r2)


def test_learns_a_heat_effect_and_beats_the_base_forecast():
    d = _daily()
    e = _errors(d, heat_effect=-0.02)
    res = driver_layer(e, d, "milk_baseline")
    late = lambda x: x[pd.to_datetime(x["origin"]) >= "2019-01-01"]
    # removes more than half of the error (the rest is the 1 % noise built in)
    assert 1 - _acc(late(res.errors)) < 0.5 * (1 - _acc(late(e)))
    c = res.coefficients
    last = c[c["origin"] == c["origin"].max()].set_index("feature")
    assert last.loc["thi_anom_28d", "coef"] < 0 or last.loc["thi_28d", "coef"] < 0


def test_late_sensor_stays_in_shadow_then_probation():
    d = _daily(sensors_from=date(2022, 6, 1))
    res = driver_layer(_errors(d), d, "milk_baseline", cfg=DriverConfig(min_rows=24, active_rows=72))
    c = res.coefficients[res.coefficients["feature"] == "sessions_per_cow_28d"].set_index("origin")
    assert c.loc[date(2022, 3, 7), "status"] == SHADOW and c.loc[date(2022, 3, 7), "coef"] == 0.0
    assert c.loc[c.index.max(), "status"] in (PROBATION, ACTIVE)
    assert c.loc[c.index.max(), "status"] == PROBATION  # about 1 year of rows < 72


def test_zeros_after_recording_stops_are_missing_not_zero():
    d = _daily(mastitis_until=date(2020, 1, 1))
    b = FeatureBuilder(d, DriverConfig(stop_days=180))
    assert np.isfinite(b.row(date(2019, 6, 3), date(2019, 6, 24), date(2019, 7, 1))["mastitis_per_cow_28d"])
    assert np.isnan(b.row(date(2021, 6, 7), date(2021, 6, 28), date(2021, 7, 5))["mastitis_per_cow_28d"])
    assert np.isnan(b.row(date(2016, 1, 4), date(2016, 1, 25), date(2016, 2, 1))["sessions_per_cow_28d"])


def test_noise_only_features_are_shrunk():
    d = _daily()
    e = _errors(d, heat_effect=0.0)
    res = driver_layer(e, d, "milk_baseline")
    late = res.coefficients[res.coefficients["origin"] >= date(2022, 1, 1)]
    assert late["coef"].abs().max() < 0.01
    assert abs(_acc(res.errors) - _acc(e)) < 0.005
