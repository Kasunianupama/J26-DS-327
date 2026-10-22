"""Fictional approved aggregates only; pure comparisons, no DB/files/network."""
from datetime import date, timedelta
import json
import pytest
from components.member4_crisis_forecasting.services.aggregate_calibration import CalibrationPlan, compare_calibration, diagnostics
from components.member4_crisis_forecasting.tests.test_research_outputs import synthetic_row, research_config, GENERATED
from components.member4_crisis_forecasting.tests.test_scoring_output import configuration, rule


def config():
    return research_config(scoring=configuration(operational_rules=(rule('n_blood_alarms', upper=12),)))


def plan(**changes):
    values = dict(reference_start=date(2025, 1, 1), reference_end=date(2025, 1, 6),
        comparison_start=date(2025, 1, 7), comparison_end=date(2025, 1, 12),
        upper_percentile=80, minimum_days=6, new_version='fictional-candidate-v2',
        recording_regime_note='Synthetic regime assumption only, not verified recording quality.')
    values.update(changes)
    return CalibrationPlan(**values)


def rows():
    return [synthetic_row(date=date(2025, 1, 1)+timedelta(days=i), mastitis_episodes=0,
        udder_teat_episodes=0, other_health_episodes=None, n_blood_alarms=20+i,
        n_sessions=100, n_conductivity_alarms=None) for i in range(12)]


def compare(data=None, **changes):
    return compare_calibration(rows() if data is None else data, config(), plan(**changes), generated_at=GENERATED, data_kind='synthetic')


def test_zero_missing_health_and_unknown_completeness_remain_distinct():
    report = diagnostics(rows(), date(2025, 1, 1), date(2025, 1, 12), config())
    assert report['indicators']['mastitis_episodes']['zero'] == 12
    assert report['indicators']['other_health_episodes']['missing'] == 12
    assert report['health_interpretation']['status'] == 'unverified'
    assert report['alarm_compatibility']['n_blood_alarms']['rate_status'].startswith('deferred')


def test_empirical_reference_only_new_config_and_no_original_mutation():
    original = config(); before = original.model_dump(mode='json')
    report, candidate = compare_calibration(rows(), original, plan(), generated_at=GENERATED, data_kind='synthetic')
    assert original.model_dump(mode='json') == before
    assert candidate.scoring.operational_rules[0].upper == 24
    assert candidate.scoring.version == 'fictional-candidate-v2'
    assert candidate.scoring.biological_rules == original.scoring.biological_rules
    assert candidate.scoring.operational_weight == original.scoring.operational_weight
    assert report['old_configuration_recomputed_on_current_snapshot']['scores']['operational']['at_100'] == 6
    assert report['publication'] == 'disabled_no_writes'
    assert report['published_output_equivalence'].startswith('not_verified')


def test_future_comparison_values_never_fit_threshold():
    data = rows()
    for i in range(6, 12): data[i] = data[i].model_copy(update={'n_blood_alarms': 100000})
    _, candidate = compare(data)
    assert candidate.scoring.operational_rules[0].upper == 24


@pytest.mark.parametrize('kind', ['gap', 'missing', 'constant', 'zero_sessions'])
def test_unreliable_reference_withholds_proposal(kind):
    data = rows()
    if kind == 'gap': data.pop(0)
    if kind == 'missing': data[0] = data[0].model_copy(update={'n_blood_alarms': None})
    if kind == 'constant': data = [row.model_copy(update={'n_blood_alarms': 20}) for row in data]
    if kind == 'zero_sessions': data[0] = data[0].model_copy(update={'n_sessions': 0})
    report, candidate = compare(data)
    assert candidate is None and report['proposal_status'] == 'unavailable'
    assert report['blockers']


def test_temporal_overlap_and_duplicate_dates_rejected():
    with pytest.raises(ValueError): plan(reference_end=date(2025, 1, 7))
    with pytest.raises(ValueError): compare(rows()+[rows()[0]])
    with pytest.raises(ValueError): compare(new_version=config().scoring.version)


def test_summary_has_no_row_level_payloads_and_rates_never_calculated():
    report, _ = compare()
    text = json.dumps(report, default=str)
    for forbidden in ('output_id', 'assessment_date', 'recorded_count', 'ratio_per_session', 'password'):
        assert forbidden not in text
    assert report['rates'].startswith('not_calculated')
    assert report['monthly_diagnostics']['2025-01']['available_days'] == 12
