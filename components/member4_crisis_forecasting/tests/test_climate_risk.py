"""All thresholds and records here are fictional synthetic test choices."""

from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from components.member4_crisis_forecasting.climate.climate_features import BaselineConfig, fit_thi_baseline
from components.member4_crisis_forecasting.climate.environmental_risk import ClimateConfig, assess_climate
from components.member4_crisis_forecasting.schemas.daily_inputs import DailyInputBatch, DailyRiskInput


def day(index, thi, **changes):
    end = datetime(2020, 1, 1, 23, tzinfo=timezone.utc) + timedelta(days=index)
    values = dict(observation_date=end.date(), observation_end=end, available_at=end,
                  source="synthetic", source_version="fictional-v1", quality="ok", thi_mean=thi)
    values.update(changes)
    return DailyRiskInput(**values)


def baseline(records=None, minimum=3):
    records = records if records is not None else (day(0, 10), day(1, 20), day(2, 30))
    return fit_thi_baseline(
        DailyInputBatch(assessment_cutoff=day(9, 0).available_at, days=records),
        BaselineConfig(training_start=date(2020, 1, 1), training_end=date(2020, 1, 3),
                       percentile=50, minimum_days=minimum),
    )


def assess(value, threshold=15, reference=None, **changes):
    record = day(10, value, **changes)
    return assess_climate(record, record.available_at,
                          ClimateConfig(heat_stress_threshold=threshold), reference)


def test_absolute_and_relative_heat_are_distinct_and_deterministic():
    reference = baseline()
    result = assess(18, reference=reference)
    assert result == assess(18, reference=reference)
    assert result.status == "available"
    assert result.above_heat_threshold is True
    assert result.absolute_exceedance == 3
    assert result.unusually_high is False
    assert result.historical_exceedance == 0
    assert "not a trained ML prediction" in result.explanation[0]


def test_relative_heat_can_exceed_without_absolute_heat():
    result = assess(25, threshold=30, reference=baseline())
    assert result.above_heat_threshold is False
    assert result.unusually_high is True
    assert result.historical_exceedance == 5


def test_equal_threshold_is_not_exceeded():
    result = assess(20, threshold=20, reference=baseline())
    assert result.above_heat_threshold is False
    assert result.unusually_high is False


def test_zero_is_a_valid_observation():
    assert assess(0).absolute_exceedance == 0
    assert assess(0).status == "partial"


@pytest.mark.parametrize("changes", [{"thi_mean": None}, {"quality": "partial"}, {"quality": "unavailable"}])
def test_unusable_day_is_withheld(changes):
    changes = dict(changes)
    value = changes.pop("thi_mean", 25)
    result = assess(value, **changes)
    assert result.status == "unavailable"
    assert result.above_heat_threshold is None


def test_absent_configuration_is_explicit():
    result = assess(25, threshold=None)
    assert result.absolute_exceedance is None
    assert result.unusually_high is None
    assert len(result.explanation) == 3


def test_insufficient_baseline_does_not_disable_absolute_comparison():
    result = assess(25, reference=baseline(minimum=4))
    assert result.above_heat_threshold is True
    assert result.unusually_high is None
    assert result.status == "partial"


def test_future_test_values_do_not_change_baseline():
    reference = baseline()
    changed = baseline((day(0, 10), day(1, 20), day(2, 30), day(4, 9999)))
    assert reference.threshold == changed.threshold == 20
    assert changed.excluded_days == 1


def test_missing_and_bad_quality_training_days_are_excluded_but_zero_is_kept():
    reference = baseline((day(0, 0), day(1, None), day(2, 30, quality="partial")), minimum=2)
    assert reference.usable_days == 1
    assert reference.excluded_days == 2
    assert reference.threshold is None


def test_empty_baseline_is_insufficient():
    assert baseline(()).status == "insufficient_data"


def test_interpolated_percentile():
    assert baseline((day(0, 10), day(1, 20)), minimum=2).threshold == 15


def test_overlapping_baseline_is_rejected():
    record = day(2, 25)
    with pytest.raises(ValueError, match="precede"):
        assess_climate(record, day(12, 0).available_at, ClimateConfig(), baseline())


def test_baseline_not_available_at_cutoff_is_rejected():
    record = day(5, 25)
    with pytest.raises(ValueError, match="after assessment"):
        assess_climate(record, record.available_at, ClimateConfig(), baseline())


def test_future_day_availability_is_rejected():
    with pytest.raises(ValidationError, match="unavailable"):
        assess_climate(day(10, 25), day(9, 0).available_at, ClimateConfig())


def test_mixed_baseline_provenance_is_rejected():
    with pytest.raises(ValueError, match="one source"):
        baseline((day(0, 10), day(1, 20, source_version="other")))


def test_incompatible_assessment_provenance_is_rejected():
    with pytest.raises(ValueError, match="provenance"):
        assess(25, reference=baseline(), source_version="other")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_thresholds_and_inputs_are_rejected(value):
    with pytest.raises(ValidationError):
        ClimateConfig(heat_stress_threshold=value)
    with pytest.raises(ValidationError):
        day(0, value)


@pytest.mark.parametrize("percentile,minimum", [(0, 3), (100, 3), (50, 1), (50, True)])
def test_invalid_baseline_configuration_is_rejected(percentile, minimum):
    with pytest.raises(ValidationError):
        BaselineConfig(training_start=date(2020, 1, 1), training_end=date(2020, 1, 3),
                       percentile=percentile, minimum_days=minimum)


def test_reversed_training_window_is_rejected():
    with pytest.raises(ValueError, match="training_start"):
        fit_thi_baseline(DailyInputBatch(assessment_cutoff=day(9, 0).available_at, days=()),
                         BaselineConfig(training_start=date(2020, 1, 3), training_end=date(2020, 1, 1),
                                        percentile=50, minimum_days=2))
