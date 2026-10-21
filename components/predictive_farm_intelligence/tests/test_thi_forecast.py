"""Synthetic-only tests for the experimental THI forecast. No database access."""
from datetime import date

import numpy as np
import pandas as pd

from components.predictive_farm_intelligence.pfoi.thi_forecast import (
    _design, forecast_thi, forecast_thi_daily,
)


def _weather():
    dates = pd.date_range("2020-01-01", "2024-04-01")
    values = _design(dates) @ np.array([75.0, 4.0, -2.0, 1.0, 0.5])
    return pd.DataFrame({"date": dates, "thi_max": values, "weather_is_complete": True})


def _daily_weather(phi=0.85, sd=1.0, seed=0, start="2016-01-01", end="2024-04-01"):
    """Synthetic (fictional) weather: seasonal curve plus day-to-day AR(1) changes."""
    dates = pd.date_range(start, end)
    rng = np.random.default_rng(seed)
    anomaly = np.zeros(len(dates))
    for i in range(1, len(dates)):
        anomaly[i] = phi * anomaly[i - 1] + rng.normal(0, sd)
    values = _design(dates) @ np.array([75.0, 4.0, -2.0, 1.0, 0.5]) + anomaly
    return pd.DataFrame({"date": dates, "thi_max": values, "weather_is_complete": True})


def test_recovers_synthetic_seasonal_signal_and_requested_dates():
    result = forecast_thi(_weather(), date(2024, 1, 1), ahead_days=30)
    assert result["status"] == "experimental"
    predictions = result["predictions"]
    assert len(predictions) == 30
    assert predictions[0]["date"] == "2024-01-01"
    assert predictions[-1]["date"] == "2024-01-30"
    expected = _weather().set_index("date").loc["2024-01-01":"2024-01-30", "thi_max"]
    assert np.max(np.abs(np.array([p["thi_max"] for p in predictions]) - expected.to_numpy())) < 0.006


def test_ignores_later_weather_and_respects_publication_lag():
    days = _weather()
    origin = date(2024, 1, 1)
    original = forecast_thi(days, origin)
    assert original["trained_through"] == "2023-12-26"
    days.loc[days.date > "2023-12-26", "thi_max"] = 200.0
    assert forecast_thi(days, origin) == original


def test_incomplete_and_nonfinite_values_are_not_training_records():
    days = _weather()
    days.loc[days.date > "2023-12-20", "weather_is_complete"] = False
    days.loc[days.date > "2023-12-20", "thi_max"] = 999.0
    original = forecast_thi(days, date(2024, 1, 1))
    days.loc[days.date > "2023-12-20", "thi_max"] = np.inf
    assert forecast_thi(days, date(2024, 1, 1)) == original
    assert original["trained_through"] == "2023-12-20"


def test_withholds_forecast_for_short_or_stale_weather_history():
    days = _weather()
    for history in (days.iloc[:0], days.iloc[:100], days.loc[days.date < "2023-11-01"]):
        result = forecast_thi(history, date(2024, 1, 1))
        assert result["status"] == "unavailable"
        assert result["predictions"] == []


# --------------------------------------------------------------------------- v2 (daily changes)

def test_v2_recovers_pure_seasonal_signal():
    result = forecast_thi_daily(_weather(), date(2024, 1, 1), ahead_days=30)
    assert result["status"] == "experimental"
    expected = _weather().set_index("date").loc["2024-01-01":"2024-01-30", "thi_max"].to_numpy()
    got = np.array([p["thi_max"] for p in result["predictions"]])
    assert np.max(np.abs(got - expected)) < 0.05


def test_v2_ignores_later_weather_and_respects_publication_lag():
    days = _daily_weather()
    origin = date(2024, 1, 1)
    original = forecast_thi_daily(days, origin)
    assert original["trained_through"] == "2023-12-26"
    days.loc[days.date > "2023-12-26", "thi_max"] = 200.0
    assert forecast_thi_daily(days, origin) == original


def test_v2_withholds_forecast_for_short_or_stale_weather_history():
    days = _weather()
    for history in (days.iloc[:0], days.iloc[:100], days.loc[days.date < "2023-11-01"]):
        result = forecast_thi_daily(history, date(2024, 1, 1))
        assert result["status"] == "unavailable"
        assert result["predictions"] == []


def test_v2_follows_a_recent_hot_spell_and_fades_to_the_season():
    days = _daily_weather()
    origin = date(2024, 1, 1)
    base = forecast_thi_daily(days, origin, weather_lag_days=1)
    days.loc[(days.date >= "2023-12-25") & (days.date <= "2023-12-31"), "thi_max"] += 4.0
    hot = forecast_thi_daily(days, origin, weather_lag_days=1)
    lift = np.array([h["thi_max"] - b["thi_max"] for h, b in zip(hot["predictions"], base["predictions"])])
    assert lift[0] > 1.5           # tomorrow still carries much of the spell
    assert abs(lift[-1]) < 0.5     # 90 days ahead it is back to the seasonal curve
    assert lift[0] > lift[13] > lift[-1] - 0.1


def test_v2_learned_persistence_matches_synthetic_process():
    result = forecast_thi_daily(_daily_weather(phi=0.85), date(2024, 1, 1), weather_lag_days=1)
    # lead counted from the last known day; true one-day share after 7 days = 0.85**7 = 0.32
    assert 0.15 < result["persistence_by_lead"]["7"] < 0.5
    assert abs(result["persistence_by_lead"]["30"]) < 0.1
    assert "60" not in result["persistence_by_lead"]  # beyond 30 days: seasonal only


def test_v2_probabilities_and_band_are_consistent():
    result = forecast_thi_daily(_daily_weather(), date(2024, 1, 1), thresholds={"p75": 77.0, "p90": 79.0})
    assert result["thresholds"] == {"p75": 77.0, "p90": 79.0}
    for p in result["predictions"]:
        assert 0.0 <= p["p_above"]["p90"] <= p["p_above"]["p75"] <= 1.0
        assert p["lower"] <= p["thi_max"] <= p["upper"]


def test_v2_beats_v1_at_short_leads_on_synthetic_daily_changes():
    """Capability check on fictional data only; real accuracy needs the owner's back-test."""
    from components.predictive_farm_intelligence.pfoi.thi_backtest import (
        run_thi_backtest, summarise, weekly_origins,
    )
    days = _daily_weather(seed=3)
    rows, _ = run_thi_backtest(days, weekly_origins(date(2022, 1, 1), date(2023, 1, 1), 14),
                               lag=1, ahead=30, score_until=date(2023, 3, 1))
    t = summarise(rows).set_index(["lead_days", "model"])
    assert t.loc[("1-3", "v2"), "mae"] < t.loc[("1-3", "v1"), "mae"]
    assert t.loc[("1-3", "v2"), "mae"] < t.loc[("1-3", "climatology"), "mae"]
    assert t.loc[("15-30", "v2"), "mae"] < 1.1 * t.loc[("15-30", "climatology"), "mae"]


def test_v2_hands_over_gradually_to_the_seasonal_curve_and_widens_errors():
    from components.predictive_farm_intelligence.pfoi.thi_forecast import DailyThiConfig
    days = _daily_weather()
    result = forecast_thi_daily(days, date(2024, 1, 1), weather_lag_days=1)
    full = forecast_thi_daily(days, date(2024, 1, 1), weather_lag_days=1, cfg=DailyThiConfig(taper_days=(90, 91)))
    assert result["taper_days"] == [20, 40]
    lift = lambda r: np.array([p["thi_max"] - p["seasonal"] for p in r["predictions"]])  # noqa: E731
    weight = np.clip((40 - np.arange(90)) / 20, 0, 1)    # 1 up to day 20, 0 from day 40
    assert np.allclose(lift(result), weight * lift(full), atol=0.011)  # 2-decimal rounding
    assert np.all(lift(result)[40:] == 0)
    narrow = forecast_thi_daily(days, date(2024, 1, 1), weather_lag_days=1, cfg=DailyThiConfig(error_scale=1.0))
    width = lambda r: np.mean([p["upper"] - p["lower"] for p in r["predictions"]])  # noqa: E731
    assert width(result) / width(narrow) == __import__("pytest").approx(1.1, abs=0.02)
