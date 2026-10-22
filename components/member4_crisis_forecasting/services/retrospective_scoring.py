"""Descriptive research indices; no fabricated availability or recording quality."""

from collections import Counter
from datetime import date
from statistics import fmean
from uuid import uuid4

from pydantic import Field, model_validator

from components.member4_crisis_forecasting.climate.environmental_risk import ClimateConfig
from components.member4_crisis_forecasting.farm_risk.dairy_risk_score import score_domain
from components.member4_crisis_forecasting.schemas.risk_output import (
    ResearchModel, ScoringConfig, DescriptiveRiskOutput, Provenance,
)


class RetrospectiveResearchConfig(ResearchModel):
    version: str = Field(min_length=1)
    assumptions: str = Field(min_length=1)
    scoring: ScoringConfig
    climate: ClimateConfig
    core_version: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def explicit_assumptions(self):
        if not self.version.strip() or not self.assumptions.strip() or not self.scoring.version.strip():
            raise ValueError("explicit_version_and_research_assumptions_required")
        return self


def calculate_research_outputs(rows, config, *, start_date, end_date, generated_at, data_kind):
    """No metadata-aware assessments are called with counterfeit timestamps.

    Raw recorded counts support descriptive indices only, not incidence, verified
    health/operational risk, diagnosis, or reliable live warning.
    """
    if (not date(2025, 1, 1) <= start_date <= end_date <= date(2026, 12, 31)
            or data_kind not in {"synthetic", "published"}):
        raise ValueError("invalid_research_range_or_source")
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("generation_time_requires_timezone")
    if len({row.date for row in rows}) != len(rows):
        raise ValueError("duplicate_dates")
    outputs, reasons = [], Counter()
    for row in sorted(rows, key=lambda item: item.date):
        if not start_date <= row.date <= end_date:
            continue
        if row.date > generated_at.date():
            reasons["future_observation_date_excluded"] += 1
            continue
        absolute = None if row.thi_mean is None or config.climate.heat_stress_threshold is None else max(
            0.0, row.thi_mean - config.climate.heat_stress_threshold)
        values = dict(
            climate={"absolute_exceedance": absolute, "historical_exceedance": None},
            biological={name: getattr(row, name) for name in ("mastitis_episodes", "udder_teat_episodes", "other_health_episodes")},
            operational={name: getattr(row, name) for name in ("n_sessions", "n_blood_alarms", "n_conductivity_alarms")},
        )
        for alarm in ("n_blood_alarms", "n_conductivity_alarms"):
            if row.n_sessions == 0 and getattr(row, alarm) is not None and getattr(row, alarm) > 0:
                values["operational"][alarm] = None
                reasons[f"{alarm}:inconsistent_zero_sessions"] += 1
        domains = tuple(score_domain(domain, domain_values, getattr(config.scoring, f"{domain}_rules"))
                        for domain, domain_values in values.items())
        for domain in domains:
            for indicator in domain.indicators:
                if indicator.score is None:
                    reasons[f"{domain.domain}:{indicator.feature}:missing_or_unsupported"] += 1
        contributions = {item.domain: None if item.score is None else item.score * getattr(config.scoring, f"{item.domain}_weight")
                         for item in domains}
        available = sum(item.score is not None for item in domains)
        combined = sum(contributions.values()) if available == 3 else None
        category = ("unavailable" if combined is None else "high_provisional" if combined >= config.scoring.high_starts_at else
                    "medium_provisional" if combined >= config.scoring.medium_starts_at else "low_provisional")
        outputs.append(DescriptiveRiskOutput(
            output_id=uuid4(), assessment_date=row.date, generated_at=generated_at,
            scoring_config=config.scoring, provenance=Provenance(source=data_kind, core_version=config.core_version),
            domains=domains, combined_score=combined, risk_category=category, contributions=contributions,
            available_domains=available,
            data_completeness="complete" if available == 3 else "partial" if any(d.available_indicators for d in domains) else "unavailable",
            assumptions=config.assumptions,
            explanations=("Descriptive retrospective index of recorded aggregates; recording completeness is unknown.",
                          "Observation date is not availability time; no historical cutoff is invented.",
                          "Zero recorded counts are not proof of absence of disease or operational problems.",
                          "Configured provisional ramps, domain maxima and fixed weighted sum are research assumptions.",
                          "Historical anomalies and unverified ratios remain unavailable; no missing-domain renormalization.",
                          "Provisional categories are not validated warnings; Random Forest is separate and not live-approved."),
        ))
    scores = {name: [] for name in ("climate", "biological", "operational", "combined")}
    for output in outputs:
        for domain in output.domains:
            if domain.score is not None:
                scores[domain.domain].append(domain.score)
        if output.combined_score is not None:
            scores["combined"].append(output.combined_score)
    summary = dict(status="descriptive_research_calculated", research_only=True, live_warning_allowed=False,
                   score_basis="descriptive_retrospective_unverified", recording_quality="unknown",
                   historical_availability="unknown", core_version_status="provided" if config.core_version else "unknown",
                   configuration_version=config.version, scoring_version=config.scoring.version,
                   assessment_days=len(outputs),
                   score_summaries={name: dict(n=len(values), unavailable=len(outputs)-len(values),
                       mean=fmean(values) if values else None, min=min(values) if values else None,
                       max=max(values) if values else None) for name, values in scores.items()},
                   category_counts=dict(Counter(output.risk_category for output in outputs)),
                   unavailable_reason_counts=dict(reasons),
                   note="Computational input coverage is not verified recording completeness; provisional categories are not reliable live warnings.")
    return tuple(outputs), summary
