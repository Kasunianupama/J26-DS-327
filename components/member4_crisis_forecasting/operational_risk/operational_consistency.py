"""Phase 1: recorded activity and alarm availability, not operational scoring."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from components.member4_crisis_forecasting.schemas.daily_inputs import DailyInputBatch, rate_per_session
from components.member4_crisis_forecasting.schemas.operational_inputs import (
    OperationalInput, RecordingQuality,
)

IndicatorName = Literal["n_sessions", "n_blood_alarms", "n_conductivity_alarms"]
INDICATORS: tuple[IndicatorName, ...] = (
    "n_sessions", "n_blood_alarms", "n_conductivity_alarms",
)


class OperationalIndicator(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: IndicatorName
    recorded_count: int | None = Field(ge=0, strict=True)
    recording_quality: RecordingQuality
    status: Literal["available", "missing", "unavailable"]
    ratio_per_session: float | None
    ratio_unit: Literal["events_per_session", "fraction_of_flagged_sessions"] | None
    consistency_warnings: tuple[str, ...]
    explanation: tuple[str, ...]


class OperationalAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    method: Literal["deterministic_operational_input_assessment"] = "deterministic_operational_input_assessment"
    input: OperationalInput
    assessment_cutoff: AwareDatetime
    status: Literal["available", "partial", "unavailable"]
    indicators: tuple[OperationalIndicator, ...]
    explanation: tuple[str, ...]


def assess_operational_inputs(
    inputs: OperationalInput, assessment_cutoff: AwareDatetime,
) -> OperationalAssessment:
    """Preserve counts and explain missingness separately from recording quality.

    Overall status concerns raw-input usability, not severity or ratio readiness.
    Inconsistency flags do not silently correct or discard recorded values.
    """
    batch = DailyInputBatch(assessment_cutoff=assessment_cutoff, days=(inputs.day,))
    sessions = inputs.day.n_sessions
    results = []
    for name in INDICATORS:
        count = getattr(inputs.day, name)
        quality = getattr(inputs.recording_quality, name)
        reasons = []
        warnings = []
        if count is None:
            reasons.append("Recorded value is missing; it is not replaced with zero.")
        if inputs.day.quality != "ok":
            reasons.append(f"Daily quality is {inputs.day.quality}; use is withheld.")
        if quality != "complete":
            reasons.append(f"Recording quality is {quality}; completeness is not confirmed.")
        status = ("missing" if count is None else "unavailable"
                  if inputs.day.quality != "ok" or quality != "complete" else "available")
        if status == "available":
            reasons.append("Recorded value is available with declared complete recording.")
        ratio = unit = None
        if name != "n_sessions":
            definition = (inputs.blood_definition if name == "n_blood_alarms"
                          else inputs.conductivity_definition)
            if sessions == 0 and count is not None and count > 0:
                warnings.append("Positive alarms with zero recorded sessions; compatibility requires review.")
            if (definition.denominator_compatible and definition.count_unit == "flagged_sessions"
                    and sessions is not None and count is not None and count > sessions):
                warnings.append("Flagged-session count exceeds compatible recorded sessions.")
            if definition.count_unit == "unknown" or not definition.denominator_compatible:
                reasons.append("Normalization deferred: count definition or denominator compatibility unconfirmed.")
            elif (status != "available" or inputs.recording_quality.n_sessions != "complete"
                  or sessions is None):
                reasons.append("Normalization unavailable: complete usable numerator and denominator required.")
            elif sessions == 0 or warnings:
                reasons.append("Normalization unavailable: zero denominator or inconsistent values.")
            else:
                ratio = rate_per_session(count, sessions)
                unit = ("events_per_session" if definition.count_unit == "events"
                        else "fraction_of_flagged_sessions")
                reasons.append(f"Ratio uses confirmed compatible recorded sessions; unit: {unit}.")
        elif sessions == 0:
            reasons.append("Zero sessions is preserved; it does not establish downtime or recording failure.")
        results.append(OperationalIndicator(
            name=name, recorded_count=count, recording_quality=quality, status=status,
            ratio_per_session=ratio, ratio_unit=unit, consistency_warnings=tuple(warnings),
            explanation=tuple(reasons),
        ))
    usable = sum(item.status == "available" for item in results)
    return OperationalAssessment(
        input=inputs, assessment_cutoff=batch.assessment_cutoff,
        status="available" if usable == len(results) else "partial" if usable else "unavailable",
        indicators=tuple(results), explanation=(
            "Deterministic input assessment, not a trained prediction or risk score.",
            "Alarms do not establish equipment failure, worker error, or confirmed animal disease.",
            "Alarm categories are separate; overlap and attribution to biological risk remain unverified.",
        ),
    )

