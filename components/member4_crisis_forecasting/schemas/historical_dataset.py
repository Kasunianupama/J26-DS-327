"""Approved 14-column aggregate boundary plus separately supplied metadata."""

from datetime import date as Date
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from components.member4_crisis_forecasting.schemas.biological_inputs import HealthRecordingQuality
from components.member4_crisis_forecasting.schemas.operational_inputs import AlarmDefinition, OperationalRecordingQuality


class ApprovedAggregate(BaseModel):
    """All columns must be present; nullable values remain distinct from omissions."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    date: Date
    target_source: Literal["shipment", "delpro"] | None
    target_litres_per_cow: float | None = Field(ge=0, strict=True)
    is_scoreable: bool = Field(strict=True)
    milking: float | None = Field(ge=0, strict=True)
    thi_mean: float | None = Field(strict=True)
    thi_max: float | None = Field(strict=True)
    hours_thi_above: float | None = Field(ge=0, le=24, strict=True)
    mastitis_episodes: int | None = Field(ge=0, strict=True)
    udder_teat_episodes: int | None = Field(ge=0, strict=True)
    other_health_episodes: int | None = Field(ge=0, strict=True)
    n_sessions: int | None = Field(ge=0, strict=True)
    n_blood_alarms: int | None = Field(ge=0, strict=True)
    n_conductivity_alarms: int | None = Field(ge=0, strict=True)


class DomainMetadata(BaseModel):
    """Actual known timestamps only; unknown information must stay absent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    observation_end: AwareDatetime | None = None
    available_at: AwareDatetime | None = None
    quality: Literal["ok", "partial", "unavailable", "unknown"] = "unknown"


class AggregateMetadata(BaseModel):
    """Metadata is date-bound; no production quality is borrowed by other domains."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    observation_date: Date
    source: Literal["synthetic", "published"]
    source_version: str | None = Field(default=None, min_length=1)
    production: DomainMetadata = Field(default_factory=DomainMetadata)
    climate: DomainMetadata = Field(default_factory=DomainMetadata)
    biological: DomainMetadata = Field(default_factory=DomainMetadata)
    operational: DomainMetadata = Field(default_factory=DomainMetadata)
    health_recording: HealthRecordingQuality = Field(default_factory=HealthRecordingQuality)
    operational_recording: OperationalRecordingQuality = Field(default_factory=OperationalRecordingQuality)
    blood_definition: AlarmDefinition = Field(default_factory=AlarmDefinition)
    conductivity_definition: AlarmDefinition = Field(default_factory=AlarmDefinition)
