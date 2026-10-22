"""Synthetic aggregates only. No database, file loaders, or environment imports."""

from datetime import datetime, timedelta, timezone

import pytest

from components.member4_crisis_forecasting.data_access.aggregate_mapper import (
    APPROVED_COLUMNS, MappingError, map_aggregate, map_aggregates,
    validate_aggregate, validate_metadata,
)
from components.member4_crisis_forecasting.schemas.historical_dataset import DomainMetadata
from components.member4_crisis_forecasting.prediction.decline_target import (
    DeclineTargetConfig, HistoricalLabelRequest, generate_decline_labels,
)
from components.member4_crisis_forecasting.climate.environmental_risk import ClimateConfig, assess_climate
from components.member4_crisis_forecasting.biological_risk.biological_assessment import assess_biological_inputs
from components.member4_crisis_forecasting.operational_risk.operational_consistency import assess_operational_inputs

START = datetime(2020, 1, 1, 23, 59, 59, tzinfo=timezone.utc)


def raw(index=0, **changes):
    values = dict(
        date=(START + timedelta(days=index)).date(), target_source="shipment",
        target_litres_per_cow=20.0, is_scoreable=True, milking=10.0,
        thi_mean=70.0, thi_max=75.0, hours_thi_above=0.0,
        mastitis_episodes=0, udder_teat_episodes=None, other_health_episodes=2,
        n_sessions=10, n_blood_alarms=0, n_conductivity_alarms=None,
    )
    values.update(changes)
    return values


def meta(index=0, **changes):
    timestamp = START + timedelta(days=index)
    timing = dict(observation_end=timestamp, available_at=timestamp, quality="ok")
    values = dict(observation_date=timestamp.date(), source="synthetic",
                  source_version="fictional-v1", production=timing, climate=timing,
                  biological=timing, operational=timing)
    values.update(changes)
    return validate_metadata(values)


def test_mapping_preserves_values_and_domains_use_existing_assessments():
    result = map_aggregate(validate_aggregate(raw()), meta())
    assert result.production.milk_source == "shipment"
    assert result.production.is_scoreable is True
    assert result.aggregate.milking == 10
    assert result.aggregate.thi_max == 75
    assert result.aggregate.hours_thi_above == 0
    assert result.biological.day.mastitis_episodes == 0
    assert result.biological.day.udder_teat_episodes is None
    assert not result.issues
    assert assess_climate(result.climate, START, ClimateConfig()).status == "partial"
    assert assess_biological_inputs(result.biological, START).status == "unavailable"
    assert result.biological.recording_quality.mastitis_episodes == "unknown"
    operational = assess_operational_inputs(result.operational, START)
    assert operational.indicators[1].ratio_per_session is None
    assert result.operational.blood_definition.count_unit == "unknown"


@pytest.mark.parametrize("column", APPROVED_COLUMNS)
def test_missing_columns_are_not_silently_null(column):
    values = raw()
    del values[column]
    with pytest.raises(MappingError, match="invalid_aggregate"):
        validate_aggregate(values)


@pytest.mark.parametrize("changes", [
    {"n_sessions": -1}, {"mastitis_episodes": True}, {"n_blood_alarms": 1.5},
    {"thi_mean": float("nan")}, {"thi_max": float("inf")},
    {"target_litres_per_cow": -1}, {"hours_thi_above": 25},
    {"milking": -1}, {"is_scoreable": "true"}, {"target_source": "unknown"},
    {"unexpected_private_field": "DO_NOT_EXPOSE"},
])
def test_invalid_values_have_safe_errors(changes):
    with pytest.raises(MappingError) as error:
        validate_aggregate(raw(**changes))
    assert str(error.value) == "invalid_aggregate_columns_or_values"
    assert error.value.__suppress_context__


def test_nulls_and_zeros_are_distinct():
    result = map_aggregate(validate_aggregate(raw(target_source=None, target_litres_per_cow=None)), meta())
    assert result.production.milk_source is None
    assert result.production.target_litres_per_cow is None
    assert result.operational.day.n_blood_alarms == 0


def test_missing_metadata_does_not_create_objects():
    result = map_aggregate(validate_aggregate(raw()))
    assert result.issues == ("missing_metadata",)
    assert result.production is result.climate is result.biological is result.operational is None


@pytest.mark.parametrize("version", [None, " "])
def test_unknown_provenance_withholds_all_domains(version):
    result = map_aggregate(validate_aggregate(raw()), meta(source_version=version))
    assert result.production is None
    assert result.issues == ("missing_source_version",)


def test_production_scoreability_does_not_establish_other_quality():
    result = map_aggregate(validate_aggregate(raw()), meta(
        climate={}, biological={}, operational={},
    ))
    assert result.production is not None
    assert result.climate is result.biological is result.operational is None
    assert len(result.issues) == 3


@pytest.mark.parametrize("quality", ["partial", "unavailable"])
def test_explicit_quality_is_preserved(quality):
    metadata = meta().model_copy(update={"production": DomainMetadata(
        observation_end=START, available_at=START, quality=quality,
    )})
    result = map_aggregate(validate_aggregate(raw()), metadata)
    assert result.production.quality == quality
    assert result.production.is_scoreable is True


@pytest.mark.parametrize("timing", [
    {"quality": "ok"},
    {"observation_end": START, "quality": "ok"},
    {"observation_end": START, "available_at": START},
])
def test_incomplete_timing_or_unknown_quality_remains_unmapped(timing):
    result = map_aggregate(validate_aggregate(raw()), meta(production=timing))
    assert result.production is None
    assert "production:missing_timing_or_quality_metadata" in result.issues


def test_invalid_timestamp_order_has_safe_domain_issue():
    result = map_aggregate(validate_aggregate(raw()), meta(production=dict(
        observation_end=START, available_at=START - timedelta(hours=1), quality="ok",
    )))
    assert result.production is None
    assert "production:invalid_metadata_timing" in result.issues


def test_invalid_metadata_is_not_exposed():
    with pytest.raises(MappingError, match="^invalid_metadata$"):
        meta(production={"available_at": "DO_NOT_EXPOSE"})


def test_metadata_date_mismatch_is_rejected():
    with pytest.raises(MappingError, match="metadata_date_mismatch"):
        map_aggregate(validate_aggregate(raw()), meta(1))


def test_sorting_preserves_source_changes_and_calendar_gaps():
    rows = [validate_aggregate(raw(2, target_source="delpro")), validate_aggregate(raw(0))]
    result = map_aggregates(rows, [meta(2), meta(0)])
    assert [item.aggregate.date for item in result] == [raw(0)["date"], raw(2)["date"]]
    assert [item.production.milk_source for item in result] == ["shipment", "delpro"]
    assert result == map_aggregates(list(reversed(rows)), [meta(0), meta(2)])


@pytest.mark.parametrize("duplicate_metadata", [True, False])
def test_duplicate_dates_are_rejected(duplicate_metadata):
    row = validate_aggregate(raw())
    with pytest.raises(MappingError, match="duplicate_dates"):
        map_aggregates([row] if duplicate_metadata else [row, row],
                       [meta(), meta()] if duplicate_metadata else [meta()])


def test_unmatched_metadata_is_rejected():
    with pytest.raises(MappingError, match="metadata_without"):
        map_aggregates([], [meta()])


@pytest.mark.parametrize("problem", [None, "source", "gap"])
def test_production_can_feed_label_generator_separately(problem):
    rows = [validate_aggregate(raw(i, target_litres_per_cow=20 if i <= 7 else 18,
                                  target_source="delpro" if problem == "source" and i == 8 else "shipment"))
            for i in range(15) if not (problem == "gap" and i == 1)]
    mapped = map_aggregates(rows, [meta(i) for i in range(15) if not (problem == "gap" and i == 1)])
    labels = generate_decline_labels(HistoricalLabelRequest(
        days=tuple(item.production for item in mapped),
        prediction_cutoffs=(START + timedelta(days=7),),
        labels_as_of=START + timedelta(days=15),
        config=DeclineTargetConfig(decline_threshold_pct=10),
    ))
    assert labels[0].label is (True if problem is None else None)
