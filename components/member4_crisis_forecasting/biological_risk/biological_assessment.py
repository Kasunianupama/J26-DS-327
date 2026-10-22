"""Phase 1: assess input availability, keeping health categories separate."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from components.member4_crisis_forecasting.schemas.biological_inputs import (
    BiologicalInput,
    RecordingQuality,
)
from components.member4_crisis_forecasting.schemas.daily_inputs import DailyInputBatch

IndicatorName = Literal["mastitis_episodes", "udder_teat_episodes", "other_health_episodes"]
INDICATORS: tuple[IndicatorName, ...] = (
    "mastitis_episodes", "udder_teat_episodes", "other_health_episodes",
)


class BiologicalIndicator(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: IndicatorName
    recorded_count: int | None = Field(ge=0, strict=True)
    recording_quality: RecordingQuality
    status: Literal["available", "missing", "unavailable"]
    explanation: tuple[str, ...]


class BiologicalAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    method: Literal["deterministic_biological_input_assessment"] = "deterministic_biological_input_assessment"
    input: BiologicalInput
    assessment_cutoff: AwareDatetime
    status: Literal["available", "partial", "unavailable"]
    indicators: tuple[BiologicalIndicator, ...]
    explanation: tuple[str, ...]


def assess_biological_inputs(
    inputs: BiologicalInput, assessment_cutoff: AwareDatetime,
) -> BiologicalAssessment:
    """Available means usable recorded input, not confirmed disease semantics.

    Missing counts take precedence in the status; quality limitations are still
    explained. Present counts remain visible even when quality withholds use.
    """
    batch = DailyInputBatch(assessment_cutoff=assessment_cutoff, days=(inputs.day,))
    indicators = []
    for name in INDICATORS:
        count = getattr(inputs.day, name)
        quality = getattr(inputs.recording_quality, name)
        reasons = []
        if count is None:
            reasons.append("Recorded count is missing; it has not been replaced with zero.")
        if inputs.day.quality != "ok":
            reasons.append(f"Daily input quality is {inputs.day.quality}; use is withheld.")
        if quality != "complete":
            reasons.append(f"Category recording quality is {quality}; completeness is not confirmed.")
        status = (
            "missing" if count is None else
            "unavailable" if inputs.day.quality != "ok" or quality != "complete" else
            "available"
        )
        if status == "available":
            reasons.append("Recorded count is available with declared complete recording.")
            if count == 0:
                reasons.append("Zero is a recorded value; it does not prove absence of disease.")
        indicators.append(BiologicalIndicator(
            name=name, recorded_count=count, recording_quality=quality,
            status=status, explanation=tuple(reasons),
        ))
    available = sum(item.status == "available" for item in indicators)
    return BiologicalAssessment(
        input=inputs, assessment_cutoff=batch.assessment_cutoff,
        status="available" if available == len(INDICATORS) else "partial" if available else "unavailable",
        indicators=tuple(indicators),
        explanation=(
            "Deterministic input assessment, not a trained prediction or clinical diagnosis.",
            "Categories remain separate because episode overlap and definitions are unverified.",
            "No combined count, disease incidence rate, threshold, risk band, or biological score is calculated.",
        ),
    )
