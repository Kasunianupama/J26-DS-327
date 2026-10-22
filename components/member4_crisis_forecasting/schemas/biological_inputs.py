"""Health-specific recording metadata around the existing daily contract."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from components.member4_crisis_forecasting.schemas.daily_inputs import DailyRiskInput

RecordingQuality = Literal["complete", "incomplete", "unavailable", "unknown"]


class HealthRecordingQuality(BaseModel):
    """Producer-supplied completeness per category; never inferred from counts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mastitis_episodes: RecordingQuality = "unknown"
    udder_teat_episodes: RecordingQuality = "unknown"
    other_health_episodes: RecordingQuality = "unknown"


class BiologicalInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    day: DailyRiskInput
    recording_quality: HealthRecordingQuality = Field(default_factory=HealthRecordingQuality)
