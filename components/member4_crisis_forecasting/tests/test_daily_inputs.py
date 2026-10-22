"""Fictional synthetic fixtures only; no application or database imports."""

import pytest
from pydantic import ValidationError

from components.member4_crisis_forecasting.schemas.daily_inputs import (
    DailyInputBatch,
    DailyRiskInput,
    rate_per_session,
)


def synthetic_day(**changes):
    values = dict(
        observation_date="2020-01-01",
        observation_end="2020-01-01T23:59:59+05:30",
        available_at="2020-01-02T01:00:00+05:30",
        source_version="synthetic-v1",
        source="synthetic",
        quality="ok",
        n_sessions=10,
    )
    values.update(changes)
    return DailyRiskInput(**values)


def test_valid_input_is_deterministic_and_preserves_missing_and_zero():
    day = synthetic_day(n_blood_alarms=0)
    assert day == synthetic_day(n_blood_alarms=0)
    assert day.n_blood_alarms == 0
    assert day.n_conductivity_alarms is None
    batch = DailyInputBatch(
        assessment_cutoff=day.available_at, days=(day,)
    )
    assert batch.days == (day,)


@pytest.mark.parametrize("changes", [
    {"n_sessions": -1}, {"n_sessions": 1.5}, {"n_sessions": True},
    {"thi_mean": float("nan")}, {"thi_mean": float("inf")},
    {"source_version": " "}, {"farm_name": "Other"},
    {"available_at": "2020-01-02T01:00:00"},
    {"available_at": "2020-01-01T01:00:00+05:30"},
    {"observation_end": "2020-01-02T00:00:00+05:30"},
])
def test_invalid_daily_input_is_rejected(changes):
    with pytest.raises(ValidationError):
        synthetic_day(**changes)


def test_duplicate_days_are_rejected():
    day = synthetic_day()
    with pytest.raises(ValidationError, match="duplicate"):
        DailyInputBatch(assessment_cutoff=day.available_at, days=(day, day))


def test_future_availability_is_rejected():
    with pytest.raises(ValidationError, match="unavailable"):
        DailyInputBatch(
            assessment_cutoff="2020-01-02T00:00:00+05:30",
            days=(synthetic_day(),),
        )


def test_cutoff_requires_timezone():
    with pytest.raises(ValidationError):
        DailyInputBatch(assessment_cutoff="2020-01-02T00:00:00", days=())


@pytest.mark.parametrize("count,sessions,expected", [
    (None, 10, None), (0, 10, 0), (2, 10, 0.2),
    (1, 0, None), (0, None, None), (12, 10, 1.2),
])
def test_rate_distinguishes_missing_zero_and_multiple_events(count, sessions, expected):
    assert rate_per_session(count, sessions) == expected


@pytest.mark.parametrize("count,sessions", [(-1, 10), (1, -1), (True, 10), (1, 1.5)])
def test_rate_rejects_invalid_counts(count, sessions):
    with pytest.raises(ValueError):
        rate_per_session(count, sessions)
