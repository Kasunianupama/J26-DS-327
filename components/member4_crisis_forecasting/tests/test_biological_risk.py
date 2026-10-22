"""Fictional synthetic aggregate inputs only; no backend or database imports."""

import pytest
from pydantic import ValidationError

from components.member4_crisis_forecasting.biological_risk.biological_assessment import (
    INDICATORS, assess_biological_inputs,
)
from components.member4_crisis_forecasting.schemas.biological_inputs import BiologicalInput
from components.member4_crisis_forecasting.schemas.daily_inputs import DailyRiskInput


def synthetic_input(counts=None, qualities=None, daily_quality="ok"):
    day = DailyRiskInput(
        observation_date="2020-01-01", observation_end="2020-01-01T23:00:00+05:30",
        available_at="2020-01-02T01:00:00+05:30", source="synthetic",
        source_version="fictional-v1", quality=daily_quality, **(counts or {}),
    )
    return BiologicalInput(day=day, recording_quality=qualities or {})


def assess(inputs):
    return assess_biological_inputs(inputs, inputs.day.available_at)


def test_separate_counts_deterministic_results_and_no_scoring():
    inputs = synthetic_input(dict(zip(INDICATORS, (0, 2, 4))),
                             dict.fromkeys(INDICATORS, "complete"))
    result = assess(inputs)
    assert result == assess(inputs)
    assert result.status == "available"
    assert [item.recorded_count for item in result.indicators] == [0, 2, 4]
    assert [item.name for item in result.indicators] == list(INDICATORS)
    assert all(item.status == "available" for item in result.indicators)
    assert "does not prove absence" in result.indicators[0].explanation[-1]
    assert set(result.model_dump()) == {
        "method", "input", "assessment_cutoff", "status", "indicators", "explanation",
    }


def test_zero_missing_and_unavailable_are_distinct():
    result = assess(synthetic_input(
        {"mastitis_episodes": 0, "other_health_episodes": 0},
        {"mastitis_episodes": "complete", "udder_teat_episodes": "complete",
         "other_health_episodes": "unavailable"},
    ))
    assert result.status == "partial"
    assert [(item.recorded_count, item.status) for item in result.indicators] == [
        (0, "available"), (None, "missing"), (0, "unavailable"),
    ]


def test_all_missing_and_unknown_is_unavailable():
    result = assess(synthetic_input())
    assert result.status == "unavailable"
    assert all(item.status == "missing" for item in result.indicators)
    assert all(item.recording_quality == "unknown" for item in result.indicators)
    assert all(len(item.explanation) == 2 for item in result.indicators)


@pytest.mark.parametrize("quality", ["incomplete", "unavailable", "unknown"])
def test_noncomplete_quality_preserves_counts_but_withholds_use(quality):
    result = assess(synthetic_input(dict.fromkeys(INDICATORS, 3),
                                   dict.fromkeys(INDICATORS, quality)))
    assert result.status == "unavailable"
    assert all(item.recorded_count == 3 and item.status == "unavailable"
               for item in result.indicators)
    assert quality in result.indicators[0].explanation[0]


@pytest.mark.parametrize("quality", ["partial", "unavailable"])
def test_daily_quality_cannot_be_overridden_by_category_quality(quality):
    result = assess(synthetic_input(dict.fromkeys(INDICATORS, 0),
                                   dict.fromkeys(INDICATORS, "complete"), quality))
    assert result.status == "unavailable"
    assert all(item.status == "unavailable" for item in result.indicators)


@pytest.mark.parametrize("name", INDICATORS)
@pytest.mark.parametrize("value", [-1, 1.5, True, "2", float("nan")])
def test_invalid_counts_rejected(name, value):
    with pytest.raises(ValidationError):
        synthetic_input({name: value})


def test_unknown_quality_label_rejected():
    with pytest.raises(ValidationError):
        synthetic_input(qualities={"mastitis_episodes": "good"})


def test_misspelled_quality_field_rejected():
    with pytest.raises(ValidationError):
        synthetic_input(qualities={"mastitis_episode": "complete"})


def test_future_availability_rejected():
    with pytest.raises(ValidationError, match="unavailable"):
        assess_biological_inputs(synthetic_input(), "2020-01-02T00:00:00+05:30")


def test_naive_cutoff_rejected():
    with pytest.raises(ValidationError):
        assess_biological_inputs(synthetic_input(), "2020-01-02T02:00:00")
