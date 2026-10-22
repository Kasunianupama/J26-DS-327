"""Explicit local verification documents; no inferred research or quality values."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, StringConstraints, model_validator

from components.member4_crisis_forecasting.climate.environmental_risk import ClimateConfig
from components.member4_crisis_forecasting.climate.climate_features import ThiBaseline
from components.member4_crisis_forecasting.schemas.historical_dataset import AggregateMetadata
from components.member4_crisis_forecasting.schemas.risk_output import ResearchModel, ScoringConfig

Version = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class VerificationConfig(ResearchModel):
    version: Version
    scoring: ScoringConfig
    climate: ClimateConfig
    climate_baseline: ThiBaseline | None = None

    @model_validator(mode="after")
    def explicit_scoring_version(self):
        if not self.scoring.version.strip() or not self.scoring.rationale.strip():
            raise ValueError("nonblank_scoring_version_and_rationale_required")
        return self


class VerificationDate(ResearchModel):
    metadata: AggregateMetadata
    assessment_cutoff: AwareDatetime
    availability_evidence: Literal["unknown", "verified"] = "unknown"


class VerificationMetadata(ResearchModel):
    version: Version
    quality_policy_version: Version
    days: tuple[VerificationDate, ...]

    @model_validator(mode="after")
    def unique_dates(self):
        dates = [item.metadata.observation_date for item in self.days]
        if len(dates) != len(set(dates)):
            raise ValueError("duplicate_metadata_dates")
        return self
