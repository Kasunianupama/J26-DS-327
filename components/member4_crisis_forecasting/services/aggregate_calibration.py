"""Pure aggregate diagnostics and isolated descriptive calibration comparison."""
from collections import Counter
from datetime import date
from calendar import monthrange
from math import floor
from statistics import fmean

from pydantic import Field, model_validator
from components.member4_crisis_forecasting.schemas.risk_output import ResearchModel, ScoringConfig
from components.member4_crisis_forecasting.services.retrospective_scoring import calculate_research_outputs, RetrospectiveResearchConfig

HEALTH = ('mastitis_episodes', 'udder_teat_episodes', 'other_health_episodes')
ALARMS = ('n_blood_alarms', 'n_conductivity_alarms')
FIELDS = HEALTH + ALARMS + ('n_sessions',)


class CalibrationPlan(ResearchModel):
    reference_start: date
    reference_end: date
    comparison_start: date
    comparison_end: date
    upper_percentile: float = Field(gt=0, lt=100, allow_inf_nan=False)
    minimum_days: int = Field(ge=2, strict=True)
    new_version: str = Field(min_length=1)
    recording_regime_note: str = Field(min_length=1)

    @model_validator(mode='after')
    def chronological(self):
        if not date(2025, 1, 1) <= self.reference_start <= self.reference_end < self.comparison_start <= self.comparison_end <= date(2026, 12, 31):
            raise ValueError('require_prior_reference_and_separate_later_comparison_in_2025_2026')
        if not self.new_version.strip() or not self.recording_regime_note.strip():
            raise ValueError('explicit_version_and_recording_regime_note_required')
        return self


def percentile(values, pct):
    ordered = sorted(values)
    if not ordered: return None
    position = (len(ordered) - 1) * pct / 100
    lower = floor(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def distribution(values):
    present = [value for value in values if value is not None]
    return dict(observed=len(present), missing=len(values)-len(present),
                zero=sum(value == 0 for value in present), positive=sum(value > 0 for value in present), negative=sum(value < 0 for value in present),
                mean=fmean(present) if present else None, min=min(present) if present else None,
                max=max(present) if present else None,
                percentiles={str(p): percentile(present, p) for p in (25, 50, 75, 90, 95, 99)})


def diagnostics(rows, start, end, config):
    selected = [row for row in rows if start <= row.date <= end]
    expected = (end-start).days + 1
    thresholds = {rule.feature: rule.upper for rule in config.scoring.operational_rules
                  if rule.feature in ALARMS and rule.direction == 'higher_is_riskier'}
    return dict(calendar_days=expected, available_days=len(selected), missing_calendar_days=expected-len(selected),
        indicators={field: distribution([getattr(row, field) for row in selected]) for field in FIELDS},
        health_interpretation=dict(status='unverified', recording_completeness='unknown',
            meaning='Zeros describe recorded counts, not verified absence of health problems. Upstream missing-to-zero conversion cannot be identified from these columns.'),
        alarm_compatibility={field: dict(
            paired_positive_session_days=sum(row.n_sessions is not None and row.n_sessions > 0 and getattr(row, field) is not None for row in selected),
            positive_alarm_zero_session_days=sum(row.n_sessions == 0 and getattr(row, field) is not None and getattr(row, field) > 0 for row in selected),
            alarm_above_session_days=sum(row.n_sessions is not None and getattr(row, field) is not None and getattr(row, field) > row.n_sessions for row in selected),
            at_or_above_existing_upper=sum(getattr(row, field) is not None and getattr(row, field) >= thresholds[field] for row in selected) if field in thresholds else None,
            existing_upper=thresholds.get(field), rate_status='deferred_event_definition_denominator_compatibility_and_completeness_unknown') for field in ALARMS})


def score_summary(outputs):
    summary = {}
    for name in ('climate', 'biological', 'operational', 'combined'):
        values = [output.combined_score if name == 'combined' else next(d.score for d in output.domains if d.domain == name) for output in outputs]
        summary[name] = {**distribution(values), 'at_100': sum(value == 100 for value in values),
                         'at_0': sum(value == 0 for value in values)}
    return dict(days=len(outputs), scores=summary, categories=dict(Counter(o.risk_category for o in outputs)))


def compare_calibration(rows, config, plan, *, generated_at, data_kind):
    if generated_at.tzinfo is None or plan.comparison_end > generated_at.date():
        raise ValueError('aware_cutoff_and_no_future_observation_dates_required')
    if len({row.date for row in rows}) != len(rows): raise ValueError('duplicate_dates')
    if plan.new_version in (config.version, config.scoring.version): raise ValueError('new_version_required')
    reference = [row for row in rows if plan.reference_start <= row.date <= plan.reference_end]
    expected = (plan.reference_end-plan.reference_start).days + 1
    proposed_rules, candidates, blockers = [], {}, []
    for rule in config.scoring.operational_rules:
        if rule.feature not in ALARMS:
            if rule.feature.endswith('_per_session'): blockers.append('rates_not_supported_by_approved_metadata')
            proposed_rules.append(rule)
            continue
        if rule.direction != 'higher_is_riskier':
            blockers.append(f'{rule.feature}:unsupported_direction'); continue
        values = [getattr(row, rule.feature) for row in reference]
        present = [v for v in values if v is not None]
        if len(reference) != expected or len(present) != expected or len(present) < plan.minimum_days:
            blockers.append(f'{rule.feature}:incomplete_or_insufficient_reference'); continue
        if any(row.n_sessions == 0 and getattr(row, rule.feature) > 0 for row in reference):
            blockers.append(f'{rule.feature}:inconsistent_zero_sessions'); continue
        upper = percentile(present, plan.upper_percentile)
        if len(set(present)) < 2 or upper <= rule.lower:
            blockers.append(f'{rule.feature}:degenerate_empirical_range'); continue
        candidates[rule.feature] = dict(old_upper=rule.upper, proposed_upper=upper,
            existing_lower=rule.lower, reference_observed_days=len(present),
            reference_at_or_above_existing_upper=sum(v >= rule.upper for v in present),
            upper_percentile=plan.upper_percentile)
        proposed_rules.append(type(rule).model_validate({**rule.model_dump(), 'upper': upper,
            'rationale': f'Experimental empirical p{plan.upper_percentile:g} from {plan.reference_start} through {plan.reference_end}; minimum support {plan.minimum_days} days. Lower bound retained. Descriptive recorded burden only, not a clinical threshold; recording completeness unknown.'}))
    if not candidates: blockers.append('no_supported_alarm_rule_candidates')
    report = dict(research_only=True, live_warning_allowed=False, publication='disabled_no_writes',
        baseline_status='retrospective_snapshot_not_point_in_time_verified', recording_completeness='unknown',
        plan=plan.model_dump(mode='json', exclude={'recording_regime_note'}),
        reference=diagnostics(rows, plan.reference_start, plan.reference_end, config),
        comparison=diagnostics(rows, plan.comparison_start, plan.comparison_end, config),
        empirical_candidates=candidates, proposal_status='unavailable' if blockers else 'provisional_candidate_only', blockers=blockers,
        rates='not_calculated_unknown_event_units_and_recording_completeness')
    report['monthly_diagnostics'] = {}
    month = plan.reference_start.replace(day=1)
    while month <= plan.comparison_end:
        end = month.replace(day=monthrange(month.year, month.month)[1])
        report['monthly_diagnostics'][month.strftime('%Y-%m')] = diagnostics(rows, max(month, plan.reference_start), min(end, plan.comparison_end), config)
        month = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
    old_outputs, _ = calculate_research_outputs(rows, config, start_date=plan.comparison_start,
        end_date=plan.comparison_end, generated_at=generated_at, data_kind=data_kind)
    report['old_configuration_recomputed_on_current_snapshot'] = score_summary(old_outputs)
    report['published_output_equivalence'] = 'not_verified_no_published_records_read'
    if blockers: return report, None
    new_scoring = ScoringConfig.model_validate({**config.scoring.model_dump(), 'version': plan.new_version,
        'rationale': config.scoring.rationale + ' Separately versioned prior-reference empirical alarm calibration candidate; not accepted for publication.',
        'operational_rules': [rule.model_dump() for rule in proposed_rules]})
    candidate = RetrospectiveResearchConfig.model_validate({**config.model_dump(), 'version': plan.new_version,
        'assumptions': config.assumptions + f' Candidate reference {plan.reference_start}..{plan.reference_end}, separate comparison {plan.comparison_start}..{plan.comparison_end}, p{plan.upper_percentile:g}, minimum {plan.minimum_days} days; quality and original availability remain unknown. Regime note: ' + plan.recording_regime_note,
        'scoring': new_scoring.model_dump()})
    new_outputs, _ = calculate_research_outputs(rows, candidate, start_date=plan.comparison_start,
        end_date=plan.comparison_end, generated_at=generated_at, data_kind=data_kind)
    report['proposed'] = score_summary(new_outputs)
    report['paired_operational_change'] = distribution([next(d.score for d in n.domains if d.domain == 'operational') - next(d.score for d in o.domains if d.domain == 'operational')
        for o, n in zip(old_outputs, new_outputs) if all(next(d.score for d in output.domains if d.domain == 'operational') is not None for output in (o, n))])
    report['configuration_changes'] = dict(new_version=plan.new_version, changed_features=list(candidates),
        unchanged='Health/climate rules, domain MAX, lower bounds, weights and category boundaries retained.')
    return report, candidate
