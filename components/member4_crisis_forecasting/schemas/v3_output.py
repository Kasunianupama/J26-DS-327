"""Independent two-domain V3 contract; never changes V1/V2 MAX contracts."""
from datetime import date
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, Field, model_validator
from components.member4_crisis_forecasting.schemas.risk_output import ResearchModel, IndicatorRule, DomainScore, Provenance

VERSION = 'c4-v3-climate-operational-1'
ALARMS = {'n_blood_alarms', 'n_conductivity_alarms'}


class V3Configuration(ResearchModel):
    version: Literal['c4-v3-climate-operational-1'] = VERSION
    source_scoring_version: str = Field(min_length=1)
    rationale: str = 'Provisional two-domain model; calibrated source indicator rules retained, operational mean and equal domain weights.'
    provisional: Literal[True] = True
    climate_rules: tuple[IndicatorRule, ...] = Field(min_length=1)
    operational_rules: tuple[IndicatorRule, ...] = Field(min_length=2, max_length=2)
    climate_weight: Literal[0.5] = .5
    operational_weight: Literal[0.5] = .5
    medium_starts_at: float = Field(gt=0, lt=100)
    high_starts_at: float = Field(gt=0, lt=100)

    @model_validator(mode='after')
    def configuration_valid(self):
        if self.source_scoring_version == self.version or self.medium_starts_at >= self.high_starts_at:
            raise ValueError('invalid_version_or_boundaries')
        if {r.feature for r in self.operational_rules} != ALARMS:
            raise ValueError('exactly_two_raw_alarm_rules_required')
        if len({r.feature for r in self.climate_rules}) != len(self.climate_rules) or any(r.feature not in {'absolute_exceedance', 'historical_exceedance'} for r in self.climate_rules):
            raise ValueError('invalid_climate_rules')
        return self


class V3Output(ResearchModel):
    contract_version: Literal['3.0.0'] = '3.0.0'
    output_id: UUID
    farm_id: Literal['FARM_X'] = 'FARM_X'
    assessment_date: date
    generated_at: AwareDatetime
    research_only: Literal[True] = True
    live_warning_allowed: Literal[False] = False
    model_status: Literal['provisional_two_domain_not_live_validated'] = 'provisional_two_domain_not_live_validated'
    model_name: Literal['Climate and Operational Risk Model'] = 'Climate and Operational Risk Model'
    score_basis: Literal['descriptive_retrospective_unverified'] = 'descriptive_retrospective_unverified'
    recording_quality: Literal['unknown'] = 'unknown'
    source_object: Literal['c4_output.farm_risk_assessment_v2'] = 'c4_output.farm_risk_assessment_v2'
    source_output_id: UUID
    source_payload_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    scoring_config: V3Configuration
    provenance: Provenance
    domains: tuple[DomainScore, ...] = Field(min_length=2, max_length=2)
    contributions: dict[str, float | None]
    combined_score: float | None = Field(ge=0, le=100)
    risk_category: Literal['low_provisional', 'medium_provisional', 'high_provisional', 'unavailable']
    available_domains: int = Field(ge=0, le=2)
    data_completeness: Literal['complete', 'partial', 'unavailable']
    explanations: tuple[str, ...]

    @model_validator(mode='after')
    def consistency(self):
        if not date(2026, 1, 1) <= self.assessment_date <= date(2026, 8, 20) or self.generated_at.date() < self.assessment_date:
            raise ValueError('invalid_v3_date')
        if self.output_id == self.source_output_id or self.provenance.source != 'published':
            raise ValueError('invalid_v3_provenance')
        if [d.domain for d in self.domains] != ['climate', 'operational'] or set(self.contributions) != {'climate', 'operational'}:
            raise ValueError('exactly_two_domains_required')
        for domain in self.domains:
            rules = getattr(self.scoring_config, domain.domain + '_rules')
            if [i.feature for i in domain.indicators] != [r.feature for r in rules]:
                raise ValueError('indicator_rule_alignment')
            for indicator, rule in zip(domain.indicators, rules):
                if indicator.value is None:
                    if indicator.score is not None: raise ValueError('missing_not_zero')
                    continue
                if domain.domain == 'operational' and (indicator.value < 0 or not float(indicator.value).is_integer()):
                    raise ValueError('nonnegative_alarm_count_required')
                position = min(1., max(0., (indicator.value-rule.lower)/(rule.upper-rule.lower)))
                expected = 100*(position if rule.direction == 'higher_is_riskier' else 1-position)
                if indicator.score is None or abs(expected-indicator.score) > 1e-8: raise ValueError('indicator_score_mismatch')
            available = sum(i.score is not None for i in domain.indicators)
            complete = available == len(rules)
            scores = [i.score for i in domain.indicators if i.score is not None]
            expected = (max(scores) if domain.domain == 'climate' else sum(scores)/2) if complete else None
            if (domain.score != expected or domain.configured_indicators != len(rules) or domain.available_indicators != available
                    or domain.status != ('available' if complete else 'partial' if available else 'unavailable')):
                raise ValueError('domain_calculation_mismatch')
            if self.contributions[domain.domain] != (None if expected is None else expected/2):
                raise ValueError('contribution_mismatch')
        count = sum(d.score is not None for d in self.domains)
        combined = sum(self.contributions.values()) if count == 2 else None
        category = 'unavailable' if combined is None else 'high_provisional' if combined >= self.scoring_config.high_starts_at else 'medium_provisional' if combined >= self.scoring_config.medium_starts_at else 'low_provisional'
        completeness = 'complete' if count == 2 else 'partial' if any(d.available_indicators for d in self.domains) else 'unavailable'
        if (self.available_domains != count or self.combined_score != combined or self.risk_category != category or self.data_completeness != completeness):
            raise ValueError('combined_calculation_mismatch')
        return self
