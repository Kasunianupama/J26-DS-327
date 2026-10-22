"""Aggregate-only verification. No loader, publisher, training, or file I/O."""

from collections import Counter
from datetime import date, datetime
from statistics import fmean
from uuid import uuid4

from components.member4_crisis_forecasting.data_access.aggregate_mapper import map_aggregate
from components.member4_crisis_forecasting.services.scoring_service import assess_and_score
from components.member4_crisis_forecasting.schemas.risk_output import Provenance

RAW_INDICATORS = {
    "climate": ("thi_mean", "thi_max", "hours_thi_above"),
    "biological": ("mastitis_episodes", "udder_teat_episodes", "other_health_episodes"),
    "operational": ("n_sessions", "n_blood_alarms", "n_conductivity_alarms"),
}


def baseline_eligible(baseline, day, cutoff):
    provenance_matches = (baseline.source is None or
                          (baseline.source == day.source and baseline.source_version == day.source_version))
    ready_provenance_known = (baseline.status != "ready" or
                             (baseline.source == day.source and baseline.source_version == day.source_version))
    return (baseline.fitted_as_of <= cutoff and baseline.config.training_start <= baseline.config.training_end
            and baseline.config.training_end < day.observation_date and provenance_matches and ready_provenance_known)


def verify_scoring(rows, config, metadata, *, start_date: date, end_date: date,
                   data_kind: str, generated_at: datetime):
    """Return counts/distributions only; ephemeral per-date outputs are not retained.

    Evidence must be explicitly verified; mere presence of historical timestamps
    is not proof of genuine point-in-time availability. Missing metadata withholds
    scores while preserving aggregate raw-column availability diagnostics.
    """
    if data_kind not in {"synthetic", "published"} or start_date > end_date:
        raise ValueError("invalid_verification_request")
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("timezone_aware_generation_time_required")
    if len({row.date for row in rows}) != len(rows):
        raise ValueError("duplicate_aggregate_dates")
    selected = sorted((row for row in rows if start_date <= row.date <= end_date), key=lambda row: row.date)
    by_date = {item.metadata.observation_date: item for item in metadata.days}
    reasons = Counter()
    score_values = {domain: [] for domain in (*RAW_INDICATORS, "combined")}
    categories = Counter()
    available = Counter()
    mapped_counts = Counter()
    configured_available = Counter()
    raw = {field: Counter() for fields in RAW_INDICATORS.values() for field in fields}
    for row in selected:
        for field, counts in raw.items():
            value = getattr(row, field)
            counts["missing" if value is None else "observed"] += 1
            if value == 0:
                counts["recorded_zero"] += 1
        entry = by_date.get(row.date)
        eligible_inputs = dict(climate=None, biological=None, operational=None)
        cutoff = entry.assessment_cutoff if entry is not None else None
        if entry is None:
            reasons["missing_per_date_metadata"] += 1
        elif entry.metadata.source != data_kind:
            reasons["metadata_source_mismatch"] += 1
        elif entry.availability_evidence != "verified":
            reasons["historical_availability_evidence_unknown"] += 1
        elif cutoff > generated_at or cutoff.date() < row.date:
            reasons["invalid_assessment_cutoff"] += 1
        else:
            mapped = map_aggregate(row, entry.metadata)
            # Only domain issues matter here; production is not a scoring input.
            reasons.update(issue for issue in mapped.issues if not issue.startswith("production:"))
            for domain in RAW_INDICATORS:
                candidate = getattr(mapped, domain)
                if candidate is None:
                    reasons[f"{domain}:input_unmapped"] += 1
                    continue
                day = candidate if domain == "climate" else candidate.day
                if day.available_at > cutoff:
                    reasons[f"{domain}:unavailable_at_cutoff"] += 1
                    continue
                if day.quality != "ok":
                    reasons[f"{domain}:daily_quality_{day.quality}"] += 1
                if domain == "climate" and config.climate_baseline is not None:
                    baseline = config.climate_baseline
                    if not baseline_eligible(baseline, day, cutoff):
                        # Keep independently eligible absolute heat assessment.
                        reasons["climate:historical_baseline_ineligible"] += 1
                eligible_inputs[domain] = candidate
                mapped_counts[domain] += 1
        if not any(item is not None for item in eligible_inputs.values()):
            categories["unavailable"] += 1
            for domain in RAW_INDICATORS:
                reasons[f"{domain}:domain_score_unavailable"] += 1
            continue
        baseline = config.climate_baseline
        climate = eligible_inputs["climate"]
        if baseline is not None and climate is not None and not baseline_eligible(baseline, climate, cutoff):
            baseline = None
        output = assess_and_score(
            output_id=uuid4(), assessment_date=row.date, assessment_cutoff=cutoff,
            generated_at=generated_at, config=config.scoring,
            provenance=Provenance(source=data_kind, core_version=entry.metadata.source_version,
                                  availability="verified", quality_policy_version=metadata.quality_policy_version),
            climate_input=eligible_inputs["climate"], climate_config=config.climate, climate_baseline=baseline,
            biological_input=eligible_inputs["biological"], operational_input=eligible_inputs["operational"],
        )
        categories[output.risk_category] += 1
        for domain_score in output.domains:
            domain = domain_score.domain
            for indicator in domain_score.indicators:
                key = f"{domain}:{indicator.feature}"
                if indicator.score is not None:
                    configured_available[key] += 1
                else:
                    reasons[f"{key}:unavailable"] += 1
                    if domain == "biological":
                        quality = getattr(eligible_inputs[domain].recording_quality, indicator.feature, "unknown") if eligible_inputs[domain] else "unknown"
                        if getattr(row, indicator.feature) is None:
                            reasons[f"{key}:missing_measurement"] += 1
                        if quality != "complete":
                            reasons[f"{domain}:recording_{quality}"] += 1
                    elif domain == "operational":
                        if hasattr(row, indicator.feature) and getattr(row, indicator.feature) is None:
                            reasons[f"{key}:missing_measurement"] += 1
                        reasons["operational:recording_semantics_or_consistency_unconfirmed"] += 1
                    elif domain == "climate":
                        if row.thi_mean is None:
                            reasons["climate:thi_mean_missing"] += 1
                        if indicator.feature == "absolute_exceedance" and config.climate.heat_stress_threshold is None:
                            reasons["climate:heat_threshold_unconfigured"] += 1
                        if indicator.feature == "historical_exceedance" and baseline is None:
                            reasons["climate:historical_baseline_unavailable"] += 1
                        reasons["climate:measurement_quality_threshold_or_baseline_unavailable"] += 1
            if domain_score.score is None:
                reasons[f"{domain}:domain_score_unavailable"] += 1
            else:
                available[domain] += 1
                score_values[domain].append(domain_score.score)
        if output.combined_score is not None:
            available["combined"] += 1
            score_values["combined"].append(output.combined_score)
        # Never append, serialize, publish, or print output.
    n = len(selected)
    summary = dict(
        status="verification_complete" if available["combined"] else "verification_complete_combined_scores_unavailable",
        research_only=True, live_warning_allowed=False,
        configuration_version=config.version, scoring_version=config.scoring.version,
        metadata_version=metadata.version, quality_policy_version=metadata.quality_policy_version,
        data_kind=data_kind, loaded_days=n, missing_calendar_days=(end_date - start_date).days + 1 - n,
        raw_indicator_counts={field: dict(observed=counts["observed"], missing=counts["missing"], recorded_zero=counts["recorded_zero"])
                              for field, counts in raw.items()},
        mapped_domain_days={domain: mapped_counts[domain] for domain in RAW_INDICATORS},
        score_available_days={domain: available[domain] for domain in score_values},
        configured_indicator_available_days={f"{domain}:{rule.feature}": configured_available[f"{domain}:{rule.feature}"]
                                             for domain in RAW_INDICATORS for rule in getattr(config.scoring, f"{domain}_rules")},
        score_summaries={domain: dict(n=len(values), mean=fmean(values) if values else None,
                                     min=min(values) if values else None, max=max(values) if values else None)
                         for domain, values in score_values.items()},
        category_counts=dict(categories), unavailable_reason_counts=dict(reasons),
        notes=["Raw presence and recorded zeros do not prove recording completeness or eligibility.",
               "Scores are provisional research assumptions, not probabilities, diagnoses, or reliable live warnings.",
               "Reason counts may overlap; score summaries include eligible days only, not missing days as zero.",
               "Unknown historical metadata is not reconstructed; no model training or output publishing occurs."],
    )
    return summary
