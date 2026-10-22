"""Provisional deterministic scoring over existing quality-gated assessments."""

from components.member4_crisis_forecasting.schemas.risk_output import (
    ALLOWED_FEATURES, DomainScore, FarmRiskOutput, IndicatorScore,
)


def score_domain(domain, values, rules):
    indicators = []
    for rule in rules:
        value = values.get(rule.feature)
        if value is None:
            score = None
            explanation = "Measurement, quality, compatible ratio, or configured comparison unavailable; not zero risk."
        else:
            position = min(1.0, max(0.0, (value - rule.lower) / (rule.upper - rule.lower)))
            score = 100 * (position if rule.direction == "higher_is_riskier" else 1 - position)
            explanation = (f"Provisional clipped linear ramp [{rule.lower:g}, {rule.upper:g}], "
                           f"{rule.direction}; {rule.rationale}")
        indicators.append(IndicatorScore(feature=rule.feature, value=value, score=score, explanation=explanation))
    available = sum(item.score is not None for item in indicators)
    complete = available == len(indicators)
    return DomainScore(domain=domain, status="available" if complete else "partial" if available else "unavailable",
        score=max(item.score for item in indicators) if complete else None,
        configured_indicators=len(indicators), available_indicators=available, indicators=tuple(indicators),
        explanation="Maximum configured indicator score; no sum of overlapping health/alarm categories. All configured indicators required.")


def build_farm_risk_output(*, output_id, assessment_date, assessment_cutoff, generated_at,
                           config, provenance, climate=None, biological=None, operational=None):
    """No default weights or thresholds, no RF calls, no I/O. Missing stays missing."""
    assessments = dict(climate=climate, biological=biological, operational=operational)
    domains = []
    for domain in ALLOWED_FEATURES:
        assessment = assessments[domain]
        values = {}
        if assessment is not None:
            day = assessment.input if domain == "climate" else assessment.input.day
            if (day.observation_date != assessment_date or assessment.assessment_cutoff != assessment_cutoff
                    or day.source != provenance.source or day.source_version != provenance.core_version):
                raise ValueError("assessment_date_cutoff_or_provenance_mismatch")
            if domain == "climate":
                values = {name: getattr(assessment, name) for name in ALLOWED_FEATURES[domain]}
            else:
                values = {item.name: item.recorded_count if item.status == "available" else None
                          for item in assessment.indicators}
                if domain == "operational":
                    for item in assessment.indicators:
                        if item.consistency_warnings:
                            values[item.name] = None
                        if item.name in {"n_blood_alarms", "n_conductivity_alarms"}:
                            key = "blood_alarms_per_session" if item.name == "n_blood_alarms" else "conductivity_alarms_per_session"
                            values[key] = item.ratio_per_session if not item.consistency_warnings else None
        domains.append(score_domain(domain, values, getattr(config, f"{domain}_rules")))
    contributions = {item.domain: None if item.score is None else item.score * getattr(config, f"{item.domain}_weight")
                     for item in domains}
    available = sum(item.score is not None for item in domains)
    combined = sum(contributions.values()) if available == 3 else None
    category = ("unavailable" if combined is None else "high_provisional" if combined >= config.high_starts_at else
                "medium_provisional" if combined >= config.medium_starts_at else "low_provisional")
    return FarmRiskOutput(output_id=output_id, assessment_date=assessment_date, assessment_cutoff=assessment_cutoff,
        generated_at=generated_at, scoring_config=config, provenance=provenance, domains=tuple(domains),
        combined_score=combined, risk_category=category, contributions=contributions, available_domains=available,
        data_completeness="complete" if available == 3 else "partial" if any(item.available_indicators for item in domains) else "unavailable",
        explanations=("Research-only provisional score, not disease probability or validated live warning.",
                      "Fixed weighted sum across three complete domains; no renormalization when data are missing.",
                      "Known domain contributions are shown even when combined score is withheld.",
                      "Cross-domain biological/operational overlap may remain; weights are assumptions requiring review.",
                      "Random Forest decline classification is separate and is not authorized for reliable live warnings."))

