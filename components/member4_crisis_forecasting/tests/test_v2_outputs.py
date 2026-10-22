"""Synthetic approved aggregates, configs and mocked publication only."""
from datetime import datetime, timedelta, timezone
from copy import deepcopy
import pytest
from components.member4_crisis_forecasting.tests.test_research_outputs import research_config, synthetic_row
from components.member4_crisis_forecasting.services.retrospective_scoring import RetrospectiveResearchConfig
from components.member4_crisis_forecasting.services.v2_outputs import START, END, generate_v2, validate_v2_config
from components.member4_crisis_forecasting.output.v2_publication import OBJECT, publish_v2

NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)


def configs():
    baseline = research_config()
    data = baseline.model_dump()
    data['version'] = 'fictional-v2'; data['scoring']['version'] = 'fictional-scoring-v2'
    data['scoring']['operational_rules'][0]['upper'] = 24
    return baseline, RetrospectiveResearchConfig.model_validate(data)


def generate():
    baseline, candidate = configs()
    rows = [synthetic_row(date=START+timedelta(days=i), mastitis_episodes=0, udder_teat_episodes=0,
                          n_blood_alarms=12) for i in range((END-START).days+1)]
    return generate_v2(rows, candidate, baseline, generated_at=NOW, data_kind='published')


def test_full_range_provenance_config_and_reproducible_ids():
    outputs, summary = generate()
    again, _ = generate()
    assert len(outputs) == 232 and summary['missing_calendar_days'] == 0
    assert [o.output_id for o in outputs] == [o.output_id for o in again]
    assert all(o.research_only and not o.live_warning_allowed for o in outputs)
    assert outputs[0].recording_quality == 'unknown'
    assert outputs[0].domains[1].score == 0
    assert summary['scoring_version_consistent']
    assert 'output_id' not in str(summary)


def test_non_operational_changes_and_reused_version_rejected():
    baseline, candidate = configs()
    for change in ('biological_rules', 'climate_weight'):
        data = candidate.model_dump()
        if change == 'biological_rules': data['scoring'][change][0]['upper'] += 1
        else:
            data['scoring']['climate_weight'] += .1; data['scoring']['operational_weight'] -= .1
        with pytest.raises(ValueError): validate_v2_config(RetrospectiveResearchConfig.model_validate(data), baseline)
    with pytest.raises(ValueError): validate_v2_config(baseline, baseline)


def test_approval_checked_before_connection():
    def forbidden(**kwargs): raise AssertionError('must not connect')
    with pytest.raises(PermissionError): publish_v2([], host='fictional', port=5432, password='fictional', connect=forbidden)


def test_append_only_duplicate_safe_and_conflict_rejected():
    outputs, _ = generate(); outputs = outputs[:1]
    state = {}
    calls = []
    class Fake:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def cursor(self): return self
        def execute(self, sql, params):
            calls.append(sql)
            if sql.startswith('INSERT'):
                payload = params[-1].obj
                key = payload['assessment_date']
                if key not in state:
                    state[key] = deepcopy(payload); self.result = (payload['output_id'],)
                else: self.result = None
            else: self.result = (state[params[1]],)
        def fetchone(self): return self.result
    kwargs = dict(approved_object=OBJECT, host='fictional', port=5432, password='fictional', connect=lambda **kw: Fake())
    assert publish_v2(outputs, **kwargs)['inserted'] == 1
    assert publish_v2(outputs, **kwargs)['unchanged_existing'] == 1
    state[outputs[0].assessment_date.isoformat()]['assumptions'] += ' conflicting snapshot'
    with pytest.raises(ValueError): publish_v2(outputs, **kwargs)
    assert all('farm_risk_assessment_v2' in sql for sql in calls)
    assert not any('UPDATE ' in sql or 'DELETE ' in sql for sql in calls)
