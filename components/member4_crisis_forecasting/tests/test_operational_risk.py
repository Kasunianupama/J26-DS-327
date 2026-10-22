"""Fictional synthetic inputs only; no application, data, or environment access."""

import pytest
from pydantic import ValidationError

from components.member4_crisis_forecasting.operational_risk.operational_consistency import (
    INDICATORS, assess_operational_inputs,
)
from components.member4_crisis_forecasting.schemas.operational_inputs import OperationalInput


def synthetic_input(counts=None, quality=None, definition=None, daily_quality="ok"):
    return OperationalInput(
        day=dict(observation_date="2020-01-01", observation_end="2020-01-01T23:00:00+05:30",
                 available_at="2020-01-02T01:00:00+05:30", source="synthetic",
                 source_version="fictional-v1", quality=daily_quality, **(counts or {})),
        recording_quality=quality or {}, blood_definition=definition or {},
        conductivity_definition=definition or {},
    )


def assess(inputs):
    return assess_operational_inputs(inputs, inputs.day.available_at)


COMPLETE = dict.fromkeys(INDICATORS, "complete")
EVENTS = dict(count_unit="events", denominator_compatible=True)


def test_separate_counts_deterministic_results_and_deferred_normalization():
    inputs = synthetic_input(dict(zip(INDICATORS, (10, 0, 3))), COMPLETE)
    result = assess(inputs)
    assert result == assess(inputs)
    assert result.status == "available"
    assert [item.recorded_count for item in result.indicators] == [10, 0, 3]
    assert all(item.ratio_per_session is None for item in result.indicators)
    assert "deferred" in result.indicators[1].explanation[-1]
    assert set(result.model_dump()) == {
        "method", "input", "assessment_cutoff", "status", "indicators", "explanation",
    }


def test_missing_zero_and_unavailable_remain_distinct():
    result = assess(synthetic_input(
        {"n_sessions": 0, "n_conductivity_alarms": 0},
        {**COMPLETE, "n_conductivity_alarms": "unavailable"},
    ))
    assert result.status == "partial"
    assert [(x.recorded_count, x.status) for x in result.indicators] == [
        (0, "available"), (None, "missing"), (0, "unavailable"),
    ]


@pytest.mark.parametrize("sessions,alarms,warning", [(0, 0, False), (0, 2, True), (None, 2, False)])
def test_unusable_denominator_preserves_counts(sessions, alarms, warning):
    result = assess(synthetic_input(dict(zip(INDICATORS, (sessions, alarms, alarms))), COMPLETE, EVENTS))
    alarm = result.indicators[1]
    assert alarm.recorded_count == alarms
    assert alarm.ratio_per_session is None
    assert bool(alarm.consistency_warnings) is warning


def test_multiple_events_per_session_are_allowed():
    result = assess(synthetic_input(dict(zip(INDICATORS, (10, 12, 0))), COMPLETE, EVENTS))
    assert result.indicators[1].ratio_per_session == 1.2
    assert result.indicators[1].ratio_unit == "events_per_session"
    assert not result.indicators[1].consistency_warnings
    assert result.indicators[2].ratio_per_session == 0


def test_flagged_sessions_cannot_exceed_compatible_sessions():
    definition = dict(count_unit="flagged_sessions", denominator_compatible=True)
    result = assess(synthetic_input(dict(zip(INDICATORS, (10, 12, 2))), COMPLETE, definition))
    assert result.indicators[1].recorded_count == 12
    assert result.indicators[1].consistency_warnings
    assert result.indicators[1].ratio_per_session is None
    assert result.indicators[2].ratio_per_session == 0.2
    assert result.indicators[2].ratio_unit == "fraction_of_flagged_sessions"


@pytest.mark.parametrize("definition", [{}, {"count_unit": "events"}, {"denominator_compatible": True}])
def test_each_normalization_confirmation_is_required(definition):
    result = assess(synthetic_input(dict.fromkeys(INDICATORS, 2), COMPLETE, definition))
    assert result.indicators[1].ratio_per_session is None


@pytest.mark.parametrize("name", INDICATORS)
@pytest.mark.parametrize("quality", ["incomplete", "unavailable", "unknown"])
def test_quality_withholds_only_dependent_values(name, quality):
    result = assess(synthetic_input(dict.fromkeys(INDICATORS, 2), {**COMPLETE, name: quality}, EVENTS))
    item = next(x for x in result.indicators if x.name == name)
    assert item.status == "unavailable"
    assert item.recording_quality == quality
    assert item.recorded_count == 2
    dependent = result.indicators[1:] if name == "n_sessions" else (item,)
    assert all(x.ratio_per_session is None for x in dependent)


@pytest.mark.parametrize("quality", ["partial", "unavailable"])
def test_daily_quality_cannot_be_overridden(quality):
    result = assess(synthetic_input(dict.fromkeys(INDICATORS, 2), COMPLETE, EVENTS, quality))
    assert result.status == "unavailable"
    assert all(x.ratio_per_session is None for x in result.indicators)


def test_all_missing_and_unknown_is_explicit():
    result = assess(synthetic_input())
    assert result.status == "unavailable"
    assert all(x.status == "missing" and x.recording_quality == "unknown" for x in result.indicators)


@pytest.mark.parametrize("name", INDICATORS)
@pytest.mark.parametrize("value", [-1, True, 1.5, "2", float("nan")])
def test_invalid_counts_are_rejected(name, value):
    with pytest.raises(ValidationError):
        synthetic_input({name: value})


@pytest.mark.parametrize("quality", [{"n_sessions": "good"}, {"sessions": "complete"}])
def test_invalid_quality_metadata_is_rejected(quality):
    with pytest.raises(ValidationError):
        synthetic_input(quality=quality)


@pytest.mark.parametrize("definition", [{"count_unit": "animals"}, {"denominator_compatible": "yes"}])
def test_invalid_definition_metadata_is_rejected(definition):
    with pytest.raises(ValidationError):
        synthetic_input(definition=definition)


@pytest.mark.parametrize("cutoff", ["2020-01-02T00:00:00+05:30", "2020-01-02T02:00:00"])
def test_invalid_cutoff_is_rejected(cutoff):
    with pytest.raises(ValidationError):
        assess_operational_inputs(synthetic_input(), cutoff)
