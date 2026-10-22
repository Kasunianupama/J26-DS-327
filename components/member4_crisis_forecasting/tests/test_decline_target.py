"""Synthetic production actuals and illustrative thresholds only."""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from components.member4_crisis_forecasting.prediction.decline_target import (
    DeclineTargetConfig, HistoricalLabelRequest, generate_decline_labels,
)
from components.member4_crisis_forecasting.schemas.production_inputs import ProductionDay

START = datetime(2020, 1, 1, 23, 59, 59, tzinfo=timezone.utc)


def day(index, value=20, **changes):
    timestamp = START + timedelta(days=index)
    values = dict(observation_date=timestamp.date(), observation_end=timestamp,
                  available_at=timestamp, source="synthetic", source_version="fictional-v1",
                  quality="ok", milk_source="shipment", target_litres_per_cow=value,
                  is_scoreable=True)
    values.update(changes)
    return ProductionDay(**values)


def request(days=None, threshold=10, origins=None, as_of=None):
    return HistoricalLabelRequest(
        days=tuple(days if days is not None else [day(i, 20 if i <= 7 else 18) for i in range(15)]),
        prediction_cutoffs=tuple(origins if origins is not None else [START + timedelta(days=7)]),
        labels_as_of=as_of or START + timedelta(days=30),
        config=DeclineTargetConfig(decline_threshold_pct=threshold),
    )


@pytest.mark.parametrize("future,threshold,expected,change", [
    (18, 10, True, -10), (18.01, 10, False, -9.95), (17.99, 10, True, -10.05),
    (20, 10, False, 0), (22, 10, False, 10), (0, 100, True, -100),
    (18, 11, False, -10),
])
def test_percentage_and_inclusive_configurable_boundary(future, threshold, expected, change):
    result = generate_decline_labels(request([day(i, 20 if i <= 7 else future) for i in range(15)], threshold))[0]
    assert result.label is expected
    assert result.change_pct == pytest.approx(change)
    assert result.status == "available"


def test_arithmetic_average_of_daily_per_cow_values():
    records = [day(i, 14 + 2 * i if i < 7 else 999 if i == 7 else 18) for i in range(15)]
    result = generate_decline_labels(request(records))[0]
    assert result.historical_mean == 20
    assert result.future_mean == 18
    assert result.historical_start == START.date()
    assert result.outcome_end == (START + timedelta(days=14)).date()
    assert result.label is True


@pytest.mark.parametrize("index", [0, 6, 8, 14])
def test_date_gaps_are_not_filled_with_next_available_day(index):
    records = [day(i) for i in range(16) if i != index]
    result = generate_decline_labels(request(records))[0]
    assert result.label is None
    assert result.reason == "incomplete_calendar_window"


@pytest.mark.parametrize("changes,reason", [
    ({"milk_source": "delpro"}, "mixed_milk_sources_or_provenance"),
    ({"milk_source": None}, "missing_milk_source"),
    ({"source_version": "other"}, "mixed_milk_sources_or_provenance"),
    ({"target_litres_per_cow": None}, "missing_production"),
    ({"is_scoreable": False}, "unscoreable_or_unreliable_production"),
    ({"quality": "partial"}, "unscoreable_or_unreliable_production"),
])
def test_unavailable_is_not_a_negative_label(changes, reason):
    records = [day(i) for i in range(15)]
    records[8] = day(8, **changes)
    result = generate_decline_labels(request(records))[0]
    assert result.status == "unavailable"
    assert result.label is None
    assert result.change_pct is None
    assert result.reason == reason


def test_zero_reference_is_rejected_without_division():
    result = generate_decline_labels(request([day(i, 0) for i in range(15)]))[0]
    assert result.label is None
    assert result.reason == "nonpositive_historical_baseline"


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True, "20"])
def test_invalid_production_is_rejected(value):
    with pytest.raises(ValidationError):
        day(0, value)


@pytest.mark.parametrize("value", [0, -1, 101, float("nan")])
def test_invalid_threshold_is_rejected(value):
    with pytest.raises(ValidationError):
        request(threshold=value)


def test_future_actuals_cannot_label_live_inference():
    result = generate_decline_labels(request(as_of=START + timedelta(days=7)))[0]
    assert result.label is None
    assert result.reason == "actuals_not_available_as_of_label_generation"


def test_retrospective_historical_data_cannot_enter_prediction_reference():
    records = [day(i) for i in range(15)]
    records[0] = day(0, available_at=START + timedelta(days=8))
    result = generate_decline_labels(request(records))[0]
    assert result.label is None
    assert result.reason == "historical_reference_unavailable_at_prediction_cutoff"


def test_ordering_and_determinism_and_outside_window_independence():
    records = [day(i) for i in range(16)]
    cutoffs = [START + timedelta(days=8), START + timedelta(days=7)]
    result = generate_decline_labels(request(records, origins=cutoffs))
    assert result == generate_decline_labels(request(list(reversed(records)), origins=cutoffs))
    assert result[0].origin_date < result[1].origin_date
    assert result[0] == generate_decline_labels(request(records + [day(20, 999)]))[0]


def test_duplicate_dates_are_rejected():
    with pytest.raises(ValidationError, match="duplicate"):
        request([day(0), day(0)])


def test_duplicate_origins_are_rejected():
    with pytest.raises(ValidationError, match="duplicate"):
        request(origins=[START, START])


def test_cutoffs_require_timezones():
    with pytest.raises(ValidationError):
        request(origins=[START.replace(tzinfo=None)])


def test_origin_after_label_cutoff_rejected():
    with pytest.raises(ValidationError):
        request(as_of=START)


@pytest.mark.parametrize("changes,reason", [
    ({"is_scoreable": False}, "ineligible_origin_quality"),
    ({"quality": "partial"}, "ineligible_origin_quality"),
    ({"quality": "unavailable"}, "ineligible_origin_quality"),
    ({"target_litres_per_cow": None}, "missing_origin_production_or_source"),
    ({"milk_source": None}, "missing_origin_production_or_source"),
    ({"milk_source": "delpro"}, "mixed_milk_sources_or_provenance"),
    ({"available_at": START + timedelta(days=8)}, "origin_unavailable_at_prediction_cutoff"),
])
def test_origin_eligibility_is_required_independently_of_means(changes, reason):
    records = list(request().days)
    records[7] = day(7, **changes)
    result = generate_decline_labels(request(records))[0]
    assert result.label is None
    assert result.reason == reason


def test_missing_origin_is_not_ignored():
    result = generate_decline_labels(request([day(i) for i in range(15) if i != 7]))[0]
    assert result.label is None
    assert result.reason == "missing_origin_day"


@pytest.mark.parametrize("origin_value", [0, 999])
def test_eligible_origin_value_does_not_change_either_mean(origin_value):
    records = list(request().days)
    records[7] = day(7, origin_value)
    result = generate_decline_labels(request(records))[0]
    assert result.historical_mean == 20
    assert result.future_mean == 18
    assert result.change_pct == -10
    assert result.label is True
