"""Deterministic daily THI assessment, not trained prediction or diagnosis."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from components.member4_crisis_forecasting.climate.climate_features import ThiBaseline
from components.member4_crisis_forecasting.schemas.daily_inputs import DailyInputBatch, DailyRiskInput


class ClimateConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    heat_stress_threshold: float | None = Field(default=None, allow_inf_nan=False)


class ClimateAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    method: Literal["deterministic_thi_assessment"] = "deterministic_thi_assessment"
    input: DailyRiskInput
    assessment_cutoff: AwareDatetime
    status: Literal["available", "partial", "unavailable"]
    heat_stress_threshold: float | None
    absolute_exceedance: float | None
    above_heat_threshold: bool | None
    baseline: ThiBaseline | None
    historical_exceedance: float | None
    unusually_high: bool | None
    explanation: tuple[str, ...]


def assess_climate(
    day: DailyRiskInput,
    assessment_cutoff: AwareDatetime,
    config: ClimateConfig,
    baseline: ThiBaseline | None = None,
) -> ClimateAssessment:
    """Compare daily mean THI using strict 'greater than' threshold semantics.

    Quality-partial/unavailable records are withheld conservatively. Daily mean
    exceedance cannot establish hourly exposure, milk loss, or disease risk.
    """
    batch = DailyInputBatch(assessment_cutoff=assessment_cutoff, days=(day,))
    if baseline is not None:
        if baseline.fitted_as_of > batch.assessment_cutoff:
            raise ValueError("baseline was fitted after assessment cutoff")
        if baseline.config.training_end >= day.observation_date:
            raise ValueError("baseline training window must precede assessed day")
        if baseline.source is not None and (
            baseline.source != day.source or baseline.source_version != day.source_version
        ):
            raise ValueError("baseline and assessment provenance must match")
    explanations = ["Deterministic daily mean THI assessment; not a trained ML prediction."]
    absolute = historical = None
    above = unusual = None
    if day.quality != "ok" or day.thi_mean is None:
        explanations.append("THI assessment unavailable: missing THI or input quality is not ok.")
        status = "unavailable"
    else:
        if config.heat_stress_threshold is None:
            explanations.append("Absolute heat comparison unavailable: no threshold configured.")
        else:
            absolute = max(0.0, day.thi_mean - config.heat_stress_threshold)
            above = day.thi_mean > config.heat_stress_threshold
            explanations.append(
                f"Daily mean THI {day.thi_mean:g} is {'above' if above else 'at or below'} "
                f"the configured heat threshold {config.heat_stress_threshold:g}. "
                "This does not measure hours of exposure or validate the threshold."
            )
        if baseline is None:
            explanations.append("Historical comparison unavailable: no baseline supplied.")
        elif baseline.status != "ready" or baseline.threshold is None:
            explanations.append("Historical comparison unavailable: insufficient training days.")
        else:
            historical = max(0.0, day.thi_mean - baseline.threshold)
            unusual = day.thi_mean > baseline.threshold
            explanations.append(
                f"THI is {'above' if unusual else 'at or below'} the training-window "
                f"percentile {baseline.config.percentile:g} threshold {baseline.threshold:g}, "
                f"fitted from {baseline.usable_days} days. Unusual heat is distinct "
                "from absolute heat stress; this baseline is not seasonally adjusted."
            )
        status = "available" if above is not None and unusual is not None else "partial"
    return ClimateAssessment(
        input=day, assessment_cutoff=batch.assessment_cutoff, status=status,
        heat_stress_threshold=config.heat_stress_threshold, absolute_exceedance=absolute,
        above_heat_threshold=above, baseline=baseline, historical_exceedance=historical,
        unusually_high=unusual, explanation=tuple(explanations),
    )

