"""Scenarios 'like last time' on SYNTHETIC daily aggregates and error tables."""
from datetime import date, timedelta

import numpy as np
import pandas as pd

from components.predictive_farm_intelligence.pfoi.scenarios import (
    apply_scenario, detect_episodes, episode_response, narrative, summarize_response,
)

SPELLS = (date(2018, 3, 5), date(2019, 9, 2), date(2021, 4, 5), date(2022, 10, 3))


def _daily(spells=SPELLS, seed=0):
    rng = np.random.default_rng(seed)
    days = pd.date_range("2015-08-01", "2023-12-31")
    doy = days.dayofyear.to_numpy()
    thi = 72 + 5 * np.sin(2 * np.pi * (doy - 100) / 365.25) + rng.normal(0, 1, len(days))
    for s in spells:
        m = (days >= pd.Timestamp(s)) & (days < pd.Timestamp(s) + pd.Timedelta(days=30))
        thi[m] += 7
    return pd.DataFrame(dict(date=days.date, weather_is_complete=True, thi_mean=thi,
                             rain_total_mm=4.0 + rng.normal(0, 0.5, len(days)).clip(-3),
                             real_abortions=rng.poisson(0.2, len(days)).astype(float),
                             mastitis_episodes=0.0))


def _errors(spells=SPELLS, effect=-0.10, bias=0.02, skip=()):
    """Weekly origins, horizons 1/4/8; actual = forecast x (1 + bias), lower by
    ``effect`` for targets ending within 60 days after a spell start."""
    rows = []
    for o in pd.date_range("2016-01-04", "2023-12-25", freq="W-MON"):
        if o.date() in skip:
            continue
        for h in (1, 4, 8):
            s = o + pd.Timedelta(days=7 * (h - 1))
            e = s + pd.Timedelta(days=7)
            hit = any(sp <= s.date() < sp + timedelta(days=60) and o.date() >= sp for sp in spells)
            a = 1000.0 * (1 + bias) * (1 + (effect if hit else 0.0))
            rows.append(dict(origin=o.date(), grain="weekly", horizon=h, period_start=s.date(),
                             period_end=e.date(), series="herd_milk", model="milk_baseline",
                             forecast=1000.0, actual=a))
    return pd.DataFrame(rows)


def test_detects_the_planted_heat_spells_and_nothing_on_calm_weather():
    ep = detect_episodes(_daily(), breaks=())
    heat = ep[ep["kind"] == "heat"]
    assert len(heat) == len(SPELLS)
    for found, planted in zip(heat["start"], SPELLS):
        assert abs((found - planted).days) <= 7
    calm = detect_episodes(_daily(spells=()), breaks=())
    assert (calm["kind"] == "heat").sum() == 0


def test_response_removes_the_models_usual_bias():
    ep = pd.DataFrame(dict(kind="heat", start=list(SPELLS), end=[s + timedelta(days=30) for s in SPELLS]))
    resp = episode_response(_errors(), ep, "milk_baseline")
    summ = summarize_response(resp).set_index("horizon")
    # actual/forecast - 1 is -0.082 in a spell and +0.02 normally: excess about -0.102
    assert np.allclose(summ["median"], -0.102, atol=0.005)
    assert (summ["n"] == len(SPELLS)).all()


def test_episodes_without_onset_forecasts_are_skipped():
    ep = pd.DataFrame(dict(kind="heat", start=list(SPELLS), end=[s + timedelta(days=30) for s in SPELLS]))
    gap = {SPELLS[0] + timedelta(days=d) for d in range(8)}  # no origin in the first week
    resp = episode_response(_errors(skip=gap), ep, "milk_baseline")
    assert resp.groupby("horizon").size().eq(len(SPELLS) - 1).all()


def test_apply_scenario_and_range_order():
    summ = pd.DataFrame(dict(kind="heat", grain="weekly", horizon=[1, 4], n=4,
                             median=[-0.05, -0.10], low=[-0.08, -0.15], high=[-0.01, -0.04]))
    base = pd.DataFrame(dict(grain="weekly", horizon=[1, 4, 8], forecast=[1000.0, 1000.0, 1000.0]))
    out = apply_scenario(base, summ, "heat").set_index("horizon")
    assert out.loc[4, "scenario_forecast"] == 900.0
    assert out.loc[4, "scenario_low"] < out.loc[4, "scenario_forecast"] < out.loc[4, "scenario_high"]
    assert np.isnan(out.loc[8, "scenario_forecast"])  # beyond the measured horizons


def test_horizons_between_measured_ones_are_interpolated():
    summ = pd.DataFrame(dict(kind="heat", grain="monthly", horizon=[1, 3], n=[4, 3],
                             median=[-0.04, -0.10], low=[-0.06, -0.14], high=[-0.02, -0.06]))
    base = pd.DataFrame(dict(grain="monthly", horizon=[1, 2, 3], forecast=1000.0))
    out = apply_scenario(base, summ, "heat").set_index("horizon")
    assert np.isclose(out.loc[2, "scenario_forecast"], 930.0)
    assert out.loc[2, "n"] == 3


def test_narrative_states_count_direction_and_range():
    summ = pd.DataFrame(dict(kind="heat", grain="weekly", horizon=[4], n=[4],
                             median=[-0.06], low=[-0.09], high=[-0.03]))
    text = narrative(summ, "heat", "weekly", 4)
    assert "4 earlier heat spells" in text and "6% below" in text and "not a proven cause" in text
    assert "No earlier" in narrative(summ, "drought", "weekly", 4)
