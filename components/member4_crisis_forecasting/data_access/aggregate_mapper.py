"""Map caller-supplied aggregates without loading data or generating labels."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from components.member4_crisis_forecasting.schemas.biological_inputs import BiologicalInput
from components.member4_crisis_forecasting.schemas.daily_inputs import DailyRiskInput
from components.member4_crisis_forecasting.schemas.historical_dataset import ApprovedAggregate, AggregateMetadata
from components.member4_crisis_forecasting.schemas.operational_inputs import OperationalInput
from components.member4_crisis_forecasting.schemas.production_inputs import ProductionDay

APPROVED_COLUMNS = tuple(ApprovedAggregate.model_fields)


class MappingError(ValueError):
    """Safe structural error containing no supplied values or record identifiers."""


@dataclass(frozen=True)
class MappedAggregate:
    aggregate: ApprovedAggregate
    metadata: AggregateMetadata | None
    production: ProductionDay | None
    climate: DailyRiskInput | None
    biological: BiologicalInput | None
    operational: OperationalInput | None
    issues: tuple[str, ...]


def validate_aggregate(record: Mapping[str, Any]) -> ApprovedAggregate:
    """Fail closed without embedding rejected values in public exceptions."""
    try:
        return ApprovedAggregate.model_validate(record)
    except ValidationError:
        raise MappingError("invalid_aggregate_columns_or_values") from None


def validate_metadata(record: Mapping[str, Any]) -> AggregateMetadata:
    try:
        return AggregateMetadata.model_validate(record)
    except ValidationError:
        raise MappingError("invalid_metadata") from None


def map_aggregate(row: ApprovedAggregate, metadata: AggregateMetadata | None = None) -> MappedAggregate:
    """Missing metadata leaves domains unmapped. Partial quality stays partial."""
    issues = []
    mapped = dict.fromkeys(("production", "climate", "biological", "operational"))
    if metadata is None:
        issues.append("missing_metadata")
    elif metadata.observation_date != row.date:
        raise MappingError("metadata_date_mismatch")
    elif metadata.source_version is None or not metadata.source_version.strip():
        issues.append("missing_source_version")
    else:
        for domain in mapped:
            timing = getattr(metadata, domain)
            if timing.observation_end is None or timing.available_at is None or timing.quality == "unknown":
                issues.append(f"{domain}:missing_timing_or_quality_metadata")
                continue
            common = dict(
                observation_date=row.date, observation_end=timing.observation_end,
                available_at=timing.available_at, source=metadata.source,
                source_version=metadata.source_version, quality=timing.quality,
            )
            try:
                if domain == "production":
                    mapped[domain] = ProductionDay(
                        **common, milk_source=row.target_source,
                        target_litres_per_cow=row.target_litres_per_cow, is_scoreable=row.is_scoreable,
                    )
                elif domain == "climate":
                    mapped[domain] = DailyRiskInput(**common, thi_mean=row.thi_mean)
                elif domain == "biological":
                    day = DailyRiskInput(**common, **{name: getattr(row, name) for name in (
                        "mastitis_episodes", "udder_teat_episodes", "other_health_episodes",
                    )})
                    mapped[domain] = BiologicalInput(day=day, recording_quality=metadata.health_recording)
                else:
                    day = DailyRiskInput(**common, **{name: getattr(row, name) for name in (
                        "n_sessions", "n_blood_alarms", "n_conductivity_alarms",
                    )})
                    mapped[domain] = OperationalInput(
                        day=day, recording_quality=metadata.operational_recording,
                        blood_definition=metadata.blood_definition,
                        conductivity_definition=metadata.conductivity_definition,
                    )
            except ValidationError:
                issues.append(f"{domain}:invalid_metadata_timing")
    return MappedAggregate(aggregate=row, metadata=metadata, issues=tuple(issues), **mapped)


def map_aggregates(
    rows: Sequence[ApprovedAggregate], metadata: Sequence[AggregateMetadata] = (),
) -> tuple[MappedAggregate, ...]:
    """Sort chronologically, preserve gaps/sources, and reject ambiguous date joins."""
    dates = [row.date for row in rows]
    meta_dates = [item.observation_date for item in metadata]
    if len(dates) != len(set(dates)) or len(meta_dates) != len(set(meta_dates)):
        raise MappingError("duplicate_dates")
    if set(meta_dates) - set(dates):
        raise MappingError("metadata_without_matching_aggregate")
    by_date = {item.observation_date: item for item in metadata}
    return tuple(map_aggregate(row, by_date.get(row.date)) for row in sorted(rows, key=lambda row: row.date))
