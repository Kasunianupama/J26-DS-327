"""Member 4 research output contract 1.0.0; no shared-contract changes."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Domain = Literal["climate", "biological", "operational"]


class ResearchModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class IndicatorRule(ResearchModel):
    feature: str
    lower: float
    upper: float
    direction: Literal["higher_is_riskier", "lower_is_riskier"]
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def ordered(self):
        if self.lower >= self.upper:
            raise ValueError("rule_lower_must_be_less_than_upper")
        return self


ALLOWED_FEATURES = {
    "climate": {"absolute_exceedance", "historical_exceedance"},
    "biological": {"mastitis_episodes", "udder_teat_episodes", "other_health_episodes"},
    "operational": {"n_sessions", "n_blood_alarms", "n_conductivity_alarms",
                    "blood_alarms_per_session", "conductivity_alarms_per_session"},
}


class ScoringConfig(ResearchModel):
    version: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    provisional: Literal[True] = True
    climate_rules: tuple[IndicatorRule, ...] = Field(min_length=1)
    biological_rules: tuple[IndicatorRule, ...] = Field(min_length=1)
    operational_rules: tuple[IndicatorRule, ...] = Field(min_length=1)
    climate_weight: float = Field(gt=0, lt=1)
    biological_weight: float = Field(gt=0, lt=1)
    operational_weight: float = Field(gt=0, lt=1)
    medium_starts_at: float = Field(gt=0, lt=100)
    high_starts_at: float = Field(gt=0, lt=100)

    @model_validator(mode="after")
    def valid_configuration(self):
        if abs(self.climate_weight + self.biological_weight + self.operational_weight - 1) > 1e-9:
            raise ValueError("domain_weights_must_sum_to_one")
        if self.medium_starts_at >= self.high_starts_at:
            raise ValueError("risk_category_boundaries_must_increase")
        for domain, allowed in ALLOWED_FEATURES.items():
            features = [rule.feature for rule in getattr(self, f"{domain}_rules")]
            if len(features) != len(set(features)) or not set(features) <= allowed:
                raise ValueError("unsupported_or_duplicate_scoring_features")
        return self


class IndicatorScore(ResearchModel):
    feature: str
    value: float | None
    score: float | None = Field(ge=0, le=100)
    explanation: str


class DomainScore(ResearchModel):
    domain: Domain
    status: Literal["available", "partial", "unavailable"]
    score: float | None = Field(ge=0, le=100)
    configured_indicators: int = Field(ge=1)
    available_indicators: int = Field(ge=0)
    indicators: tuple[IndicatorScore, ...]
    explanation: str


class Provenance(ResearchModel):
    source: Literal["synthetic", "published"]
    core_version: str | None = Field(default=None, min_length=1)
    availability: Literal["unknown", "verified"] = "unknown"
    quality_policy_version: str | None = Field(default=None, min_length=1)


class FarmRiskOutput(ResearchModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    output_id: UUID
    farm_id: Literal["FARM_X"] = "FARM_X"
    assessment_date: date
    assessment_cutoff: AwareDatetime
    generated_at: AwareDatetime
    research_only: Literal[True] = True
    live_warning_allowed: Literal[False] = False
    model_status: Literal["random_forest_experimental_not_live_validated"] = "random_forest_experimental_not_live_validated"
    scoring_config: ScoringConfig
    provenance: Provenance
    domains: tuple[DomainScore, ...]
    combined_score: float | None = Field(ge=0, le=100)
    risk_category: Literal["low_provisional", "medium_provisional", "high_provisional", "unavailable"]
    data_completeness: Literal["complete", "partial", "unavailable"]
    available_domains: int = Field(ge=0, le=3)
    contributions: dict[Domain, float | None]
    explanations: tuple[str, ...]

    @model_validator(mode="after")
    def check_consistency(self):
        if self.assessment_cutoff is not None and (self.generated_at < self.assessment_cutoff or self.assessment_cutoff.date() < self.assessment_date):
            raise ValueError("invalid_output_timing")
        if {item.domain for item in self.domains} != set(ALLOWED_FEATURES) or len(self.domains) != 3:
            raise ValueError("exactly_three_domains_required")
        count = sum(item.score is not None for item in self.domains)
        if self.available_domains != count:
            raise ValueError("domain_completeness_mismatch")
        if set(self.contributions) != set(ALLOWED_FEATURES):
            raise ValueError("three_contributions_required")
        expected = 0.0
        for item in self.domains:
            rules = getattr(self.scoring_config, f"{item.domain}_rules")
            if [indicator.feature for indicator in item.indicators] != [rule.feature for rule in rules]:
                raise ValueError("configured_indicator_alignment_mismatch")
            for indicator, rule in zip(item.indicators, rules):
                if indicator.value is None:
                    if indicator.score is not None:
                        raise ValueError("missing_value_cannot_have_score")
                else:
                    position = min(1.0, max(0.0, (indicator.value - rule.lower) / (rule.upper - rule.lower)))
                    expected_score = 100 * (position if rule.direction == "higher_is_riskier" else 1 - position)
                    if indicator.score is None or abs(indicator.score - expected_score) > 1e-8:
                        raise ValueError("indicator_ramp_score_mismatch")
            available = sum(indicator.score is not None for indicator in item.indicators)
            if item.configured_indicators != len(item.indicators) or item.available_indicators != available:
                raise ValueError("indicator_completeness_mismatch")
            complete = available == item.configured_indicators
            domain_score = max(indicator.score for indicator in item.indicators) if complete else None
            if item.score != domain_score or item.status != ("available" if complete else "partial" if available else "unavailable"):
                raise ValueError("invalid_domain_aggregation")
            contribution = None if item.score is None else item.score * getattr(self.scoring_config, f"{item.domain}_weight")
            if self.contributions[item.domain] != contribution:
                raise ValueError("invalid_domain_contribution")
            expected += contribution or 0
        any_indicator = any(item.available_indicators for item in self.domains)
        completeness = "complete" if count == 3 else "partial" if any_indicator else "unavailable"
        if self.data_completeness != completeness:
            raise ValueError("invalid_overall_completeness")
        if count < 3:
            if self.combined_score is not None or self.risk_category != "unavailable":
                raise ValueError("incomplete_domains_cannot_have_combined_score")
        else:
            category = ("high_provisional" if expected >= self.scoring_config.high_starts_at else
                        "medium_provisional" if expected >= self.scoring_config.medium_starts_at else "low_provisional")
            if self.combined_score is None or abs(self.combined_score - expected) > 1e-8 or self.risk_category != category:
                raise ValueError("combined_score_or_category_mismatch")
        return self


class DescriptiveRiskOutput(FarmRiskOutput):
    """1.1.0 adds an explicit descriptive basis, never fictional quality metadata."""

    contract_version: Literal["1.1.0"] = "1.1.0"
    assessment_cutoff: AwareDatetime | None = None
    score_basis: Literal["descriptive_retrospective_unverified"] = "descriptive_retrospective_unverified"
    recording_quality: Literal["unknown"] = "unknown"
    assumptions: str = Field(min_length=1)

    @model_validator(mode="after")
    def no_verified_metadata_claim(self):
        if self.assessment_cutoff is not None or self.provenance.availability != "unknown" or self.provenance.quality_policy_version is not None:
            raise ValueError("descriptive_output_cannot_claim_verified_metadata")
        if self.generated_at.date() < self.assessment_date:
            raise ValueError("future_descriptive_observation_not_allowed")
        return self


def validate_research_output(data):
    if data.get("contract_version") == "1.1.0":
        return DescriptiveRiskOutput.model_validate(data)
    return FarmRiskOutput.model_validate(data)
