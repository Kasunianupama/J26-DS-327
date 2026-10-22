"""Synthetic-only tests for the THI forecast back-test. No database access."""
from datetime import date

import numpy as np
import pandas as pd

from components.predictive_farm_intelligence.pfoi.thi_backtest import (
    MODELS, run_thi_backtest, summarise, weekly_origins,
)
from components.predictive_farm_intelligence.pfoi.thi_forecast import _design


def _days(seed=0):
    dates = pd.date_range("2017-01-01", "2023-06-30")
    rng = np.random.default_rng(seed)
    noise = np.convolve(rng.normal(0, 1, len(dates) + 4), np.ones(5) / 5, mode="valid")
    values = _design(dates) @ np.array([76.0, 3.0, -1.5, 0.8, 0.3]) + noise
    return pd.DataFrame({"date": dates, "thi_max": values, "weather_is_complete": True})


def test_weekly_origins_are_mondays_inside_the_block():
    o = weekly_origins(date(2022, 1, 1), date(2022, 2, 1))
    assert o[0] == date(2022, 1, 3) and all(d.weekday() == 0 for d in o)
    assert o[-1] < date(2022, 2, 1) and len(o) == 5


def test_every_model_scored_on_identical_days_and_block_end_respected():
    rows, pers = run_thi_backtest(_days(), weekly_origins(date(2022, 1, 1), date(2022, 6, 1), 14),
                                  lag=6, ahead=60, score_until=date(2022, 6, 1))
    assert set(rows["model"]) == set(MODELS)
    assert rows.groupby("model").size().nunique() == 1
    assert pd.to_datetime(rows["date"]).max() < pd.Timestamp("2022-06-01")
    assert rows["lead"].min() == 1
    assert len(pers) == rows["origin"].nunique()
    t = summarise(rows)
    assert np.allclose(t[t["model"] == "climatology"]["skill_vs_clim"], 0.0)
    assert t.groupby("lead_days")["n"].nunique().eq(1).all()
    assert t["brier_p75"].between(0, 1).all()


def test_forecasts_do_not_see_outcomes():
    days = _days()
    origins = weekly_origins(date(2022, 3, 1), date(2022, 4, 1), 7)
    rows, _ = run_thi_backtest(days, origins, lag=6, ahead=30, score_until=date(2022, 6, 1))
    changed = days.copy()
    changed.loc[changed.date > "2022-03-01", "thi_max"] += 10.0
    later, _ = run_thi_backtest(changed, origins[:1], lag=6, ahead=30, score_until=date(2022, 6, 1))
    first = rows[rows["origin"] == origins[0]].reset_index(drop=True)
    assert np.allclose(first["predicted"], later["predicted"])
    assert np.allclose(first["actual"] + 10.0, later["actual"])  # outcomes all after the cutoff


def test_incomplete_outcomes_are_not_scored():
    days = _days()
    days.loc[(days.date >= "2022-03-10") & (days.date < "2022-03-20"), "weather_is_complete"] = False
    rows, _ = run_thi_backtest(days, [date(2022, 3, 7)], lag=6, ahead=30)
    scored = pd.to_datetime(rows["date"])
    assert not ((scored >= "2022-03-10") & (scored < "2022-03-20")).any()
