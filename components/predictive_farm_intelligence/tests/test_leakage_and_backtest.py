"""Leakage guard, periods, backtest and config on SYNTHETIC data (no database)."""
from datetime import date, timedelta

import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.backtest_herd import (
    KEY_SERIES, development_origins, run_backtest, summarise,
)
from components.predictive_farm_intelligence.pfoi.config import (
    ConfigError, DatabaseSettings, EngineConfig,
)
from components.predictive_farm_intelligence.pfoi.data import (
    LeakageError, check_before, load_origin_inputs, window_start,
)
from components.predictive_farm_intelligence.pfoi.herd_engine import project
from components.predictive_farm_intelligence.pfoi.periods import aggregate, period_bounds
from components.predictive_farm_intelligence.pfoi.rates import estimate_rates

from .synthetic import FakeHerdSource

ORIGIN = date(2020, 3, 1)
QUERIES = ("cells_on", "milking_clock", "dry_clock", "heifer_clock", "exposure", "transitions",
           "panel_months", "cow_open", "preg_milking_days", "dryoff_gest", "gestation",
           "young_days", "young_exits", "births_by_sex", "calf_sex_on")


def test_check_before_rejects_origin_date():
    frame = pd.DataFrame({"x": [1], "max_date": [ORIGIN]})
    with pytest.raises(LeakageError):
        check_before(frame, ORIGIN, "t")
    ok = check_before(frame.assign(max_date=ORIGIN - timedelta(days=1)), ORIGIN, "t")
    assert "max_date" not in ok.columns


@pytest.mark.parametrize("query", QUERIES)
def test_every_query_is_guarded(query):
    with pytest.raises(LeakageError):
        load_origin_inputs(FakeHerdSource(leak=query), ORIGIN, EngineConfig())


def test_queries_never_ask_beyond_origin():
    src = FakeHerdSource()
    cfg = EngineConfig(pregnancy_check_lag_days=35)
    load_origin_inputs(src, ORIGIN, cfg)
    known_until = ORIGIN - timedelta(days=35)
    for call in src.calls:
        dates = [a for a in call[1:] if isinstance(a, date)]
        assert all(d <= ORIGIN for d in dates), call
    by_name = {c[0]: c for c in src.calls}
    assert by_name["cells_on"][1] == ORIGIN - timedelta(days=1)
    assert by_name["cow_open"][2] == known_until
    assert by_name["transitions"][2] == date(2020, 3, 1)
    assert by_name["exposure"][1] == window_start(ORIGIN, 24) == date(2018, 3, 1)


def test_future_data_does_not_change_forecast():
    def forecast(src):
        inputs = load_origin_inputs(src, ORIGIN, EngineConfig())
        return project(inputs.state, estimate_rates(inputs.rate_inputs), 200).daily

    base = forecast(FakeHerdSource())
    perturbed = forecast(FakeHerdSource(cutoff=ORIGIN, future_scale=5.0))
    pd.testing.assert_frame_equal(base, perturbed)
    changed = forecast(FakeHerdSource(cutoff=ORIGIN - timedelta(days=40), future_scale=5.0))
    assert not base.equals(changed)  # the check above is not vacuous


def test_period_bounds_and_aggregate():
    assert period_bounds(date(2020, 11, 1), "monthly", 3) == (date(2021, 1, 1), date(2021, 2, 1))
    assert period_bounds(date(2020, 3, 2), "weekly", 2) == (date(2020, 3, 9), date(2020, 3, 16))
    with pytest.raises(ValueError):
        period_bounds(date(2020, 3, 3), "weekly", 1)
    days = pd.date_range("2020-03-01", "2020-04-10").date
    daily = pd.DataFrame({"date": days, "milking": range(len(days)), "calvings": 1.0})
    out = aggregate(daily, date(2020, 3, 1), "monthly", (1, 2), ("milking",), ("calvings",))
    assert set(out["horizon"]) == {1}  # April is incomplete and dropped
    row = out.set_index("series")["value"]
    assert row["milking"] == pytest.approx(15.0)
    assert row["calvings"] == pytest.approx(31.0)


def test_backtest_monthly_runs_and_scores_both_models():
    src = FakeHerdSource()
    origins = [date(2019, 1, 1), date(2019, 6, 1), date(2023, 6, 1)]
    res = run_backtest(src, "monthly", origins=origins)
    e = res.errors
    assert set(e["model"]) == {"herd_engine", "persistence"}
    assert set(KEY_SERIES) <= set(e["series"])
    late = e[e["origin"] == date(2023, 6, 1)]
    assert late["horizon"].max() == 6  # 12-month horizon would reach the test block
    assert (pd.to_datetime(e["period_start"]).dt.date < date(2024, 1, 1)).all()
    s = summarise(e)
    assert {"mae", "rmse", "bias", "n"} <= set(s.columns)
    assert (s["mae"] >= 0).all()


def test_backtest_weekly_runs():
    res = run_backtest(FakeHerdSource(), "weekly", origins=[date(2019, 1, 7)])
    assert set(res.errors["horizon"]) == {1, 4, 8, 13}


def test_backtest_refuses_test_block():
    with pytest.raises(ValueError):
        run_backtest(FakeHerdSource(), "monthly", origins=[date(2024, 1, 1)])


def test_development_origins():
    monthly = development_origins("monthly")
    assert monthly[0] == date(2017, 1, 1) and monthly[-1] == date(2023, 12, 1)
    assert len(monthly) == 84
    weekly = development_origins("weekly")
    assert all(d.weekday() == 0 for d in weekly) and weekly[-1] < date(2024, 1, 1)


def test_database_settings_from_env_without_connecting():
    s = DatabaseSettings.from_env({"APP_DB_PFOI_PASSWORD": "dummy-test-value"})
    assert s.url.username == "farmx_model"
    assert (s.url.host, s.url.port, s.url.database) == ("localhost", 5433, "farmx_app")
    assert "dummy-test-value" not in s.url.render_as_string(hide_password=True)
    s = DatabaseSettings.from_env({"APP_DB_HOST": "dbhost", "APP_DB_PORT": "6000",
                                   "APP_DB_PFOI_USER": "someone"})
    assert (s.url.host, s.url.port, s.url.username) == ("dbhost", 6000, "someone")
    with pytest.raises(ConfigError):
        DatabaseSettings.from_env({"APP_DB_PFOI_USER": " "})
    with pytest.raises(ConfigError):
        DatabaseSettings.from_env({"PFOI_DATABASE_URL": "mssql+pyodbc://u@h/db"})
