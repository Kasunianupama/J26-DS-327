"""Proposed operational metadata; no database field mapping is assumed."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from components.member4_crisis_forecasting.schemas.daily_inputs import DailyRiskInput

RecordingQuality = Literal["complete", "incomplete", "unavailable", "unknown"]


class OperationalRecordingQuality(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    n_sessions: RecordingQuality = "unknown"
    n_blood_alarms: RecordingQuality = "unknown"
    n_conductivity_alarms: RecordingQuality = "unknown"


class AlarmDefinition(BaseModel):
    """Explicit producer confirmations, not inferred from numerical values."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    count_unit: Literal["unknown", "events", "flagged_sessions"] = "unknown"
    denominator_compatible: bool = Field(default=False, strict=True)


class OperationalInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    day: DailyRiskInput
    recording_quality: OperationalRecordingQuality = Field(default_factory=OperationalRecordingQuality)
    blood_definition: AlarmDefinition = Field(default_factory=AlarmDefinition)
    conductivity_definition: AlarmDefinition = Field(default_factory=AlarmDefinition)
