"""Pure V2 generation: isolated configuration, same descriptive scoring engine."""
from datetime import date
from uuid import UUID, uuid5
from components.member4_crisis_forecasting.services.retrospective_scoring import calculate_research_outputs
from components.member4_crisis_forecasting.schemas.risk_output import validate_research_output

START, END = date(2026, 1, 1), date(2026, 8, 20)
NAMESPACE = UUID('80279434-d167-4280-a0e4-a4917344c188')


def validate_v2_config(candidate, baseline):
    if candidate.version == baseline.version or candidate.scoring.version == baseline.scoring.version:
        raise ValueError('distinct_v2_version_required')
    if candidate.climate != baseline.climate or candidate.core_version != baseline.core_version:
        raise ValueError('climate_or_provenance_changed')
    original = baseline.scoring.model_dump()
    proposed = candidate.scoring.model_dump()
    for key in original:
        if key not in ('version', 'rationale', 'operational_rules') and original[key] != proposed[key]:
            raise ValueError('non_operational_calibration_change')
    old, new = baseline.scoring.operational_rules, candidate.scoring.operational_rules
    if len(old) != len(new): raise ValueError('operational_features_changed')
    changed = False
    for a, b in zip(old, new):
        if (a.feature, a.lower, a.direction) != (b.feature, b.lower, b.direction):
            raise ValueError('only_alarm_upper_calibration_allowed')
        if a.upper != b.upper:
            if a.feature not in ('n_blood_alarms', 'n_conductivity_alarms'):
                raise ValueError('non_alarm_threshold_changed')
            changed = True
    if not changed: raise ValueError('no_operational_calibration_change')


def generate_v2(rows, candidate, baseline, *, generated_at, data_kind):
    validate_v2_config(candidate, baseline)
    if generated_at.date() < END: raise ValueError('comparison_period_not_yet_complete')
    outputs, summary = calculate_research_outputs(rows, candidate, start_date=START, end_date=END,
                                                  generated_at=generated_at, data_kind=data_kind)
    result = []
    for output in outputs:
        payload = output.model_dump(mode='json')
        payload['output_id'] = str(uuid5(NAMESPACE, f'FARM_X:{candidate.scoring.version}:{output.assessment_date.isoformat()}'))
        result.append(validate_research_output(payload))
    summary.update(scoring_generation='v2', publication='not_requested_no_writes',
        calendar_days=(END-START).days+1, missing_calendar_days=(END-START).days+1-len(result),
        eligible_complete_assessments=sum(o.combined_score is not None for o in result),
        operational_at_100=sum(next(d.score for d in o.domains if d.domain == 'operational') == 100 for o in result),
        scoring_version_consistent=all(o.scoring_config.version == candidate.scoring.version for o in result),
        health_interpretation='unverified_recording_completeness_not_absence_of_disease',
        provenance_note='Existing candidate provenance retained; snapshot availability remains unknown.')
    from components.member4_crisis_forecasting.services.aggregate_calibration import score_summary
    summary['score_distributions'] = score_summary(result)['scores']
    return tuple(result), summary
