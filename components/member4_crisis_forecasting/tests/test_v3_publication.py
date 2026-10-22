"""Fictional V2 payloads only. No settings, private files or live DB connections."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import pytest
from components.member4_crisis_forecasting.tests.test_scoring_output import make_output, configuration, rule
from components.member4_crisis_forecasting.schemas.risk_output import validate_research_output
from components.member4_crisis_forecasting.schemas.v3_output import V3Output
from components.member4_crisis_forecasting.services.v3_outputs import generate_v3
from components.member4_crisis_forecasting.output.v3_publication import prepare_v3, publish_v3, OBJECT

NOW = datetime(2026, 10, 23, tzinfo=timezone.utc)


def source_payload():
    payload = make_output(config=configuration(operational_rules=(rule('n_blood_alarms', upper=10), rule('n_conductivity_alarms', upper=10)))).model_dump(mode='json')
    payload.update(contract_version='1.1.0', score_basis='descriptive_retrospective_unverified',
        recording_quality='unknown', assumptions='Fictional research assumptions.', assessment_date='2026-08-20',
        assessment_cutoff=None, generated_at='2026-09-01T00:00:00Z')
    payload['provenance']['source'] = 'published'
    op = payload['domains'][2]
    for item, value in zip(op['indicators'], (10, 2)):
        item.update(value=value, score=float(value*10))
    op.update(score=100., status='available', available_indicators=2)
    payload['contributions']['operational'] = 30.
    payload['combined_score'] = sum(payload['contributions'].values())
    payload['data_completeness'] = 'complete'; payload['available_domains'] = 3
    payload['risk_category'] = 'medium_provisional'
    return validate_research_output(payload).model_dump(mode='json')


def outputs(): return generate_v3([source_payload()], generated_at=NOW)[0]


def test_calculation_contract_missing_inputs_and_nonmutation():
    source = source_payload(); before = deepcopy(source)
    result, summary = generate_v3([source], generated_at=NOW)
    out = result[0]
    assert out.domains[0].model_dump(mode='json') == source['domains'][0]
    assert out.domains[1].score == 60 and out.combined_score == 55
    assert set(out.contributions) == {'climate','operational'}
    assert source == before and out.output_id != out.source_output_id
    assert out.contract_version == '3.0.0' and not out.live_warning_allowed
    assert summary['assessment_days'] == 1 and summary['missing_calendar_days'] == 231
    assert V3Output.model_validate_json(out.model_dump_json()) == out
    missing = source_payload()
    missing['domains'][2]['indicators'][1].update(value=None, score=None)
    missing['domains'][2].update(score=None, status='partial', available_indicators=1)
    missing.update(combined_score=None, risk_category='unavailable', data_completeness='partial', available_domains=2)
    missing['contributions']['operational'] = None
    assert generate_v3([missing], generated_at=NOW)[0][0].combined_score is None


def test_duplicate_dates_historical_scope_and_tampering_rejected():
    with pytest.raises(ValueError): generate_v3([source_payload(), source_payload()], generated_at=NOW)
    source = source_payload(); source['assessment_date'] = '2025-08-20'
    with pytest.raises(ValueError): generate_v3([source], generated_at=NOW)
    payload = outputs()[0].model_dump(mode='json'); payload['combined_score'] = 48.4
    with pytest.raises(ValueError): V3Output.model_validate(payload)


def test_unrounded_python_browser_preview_and_published_client_parity():
    source = source_payload()
    climate = source['domains'][0]
    climate['indicators'][0].update(value=3.2938268, score=82.34567); climate['score'] = 82.34567
    source['scoring_config']['operational_rules'][1]['upper'] = 100/25.678
    source['domains'][2]['indicators'][1].update(value=1, score=25.678)
    source['contributions']['climate'] = 82.34567 * source['scoring_config']['climate_weight']
    source['combined_score'] = sum(source['contributions'].values())
    source['risk_category'] = 'high_provisional'
    result, _ = generate_v3([source], generated_at=NOW)
    root = Path(__file__).resolve().parents[3]
    preview = (root/'frontend/src/pages/DairyCrisisForecasting/v3Preview.mjs').as_uri()
    client = (root/'frontend/src/pages/DairyCrisisForecasting/publishedV3.mjs').as_uri()
    script = f"import {{previewV3}} from {json.dumps(preview)}; import {{validatePublishedV3Rows}} from {json.dumps(client)}; let input=''; for await (const chunk of process.stdin) input+=chunk; const [source,published]=JSON.parse(input); validatePublishedV3Rows([published]); console.log(JSON.stringify(previewV3(source).combined_score));"
    completed = subprocess.run(['node','--input-type=module','-e',script], input=json.dumps([source,result[0].model_dump(mode='json')]), text=True, capture_output=True, check=True)
    assert abs(result[0].combined_score - json.loads(completed.stdout)) < 1e-12
    assert abs(result[0].combined_score - 72.592335) < 1e-10


def test_publication_approval_idempotency_and_conflicts_are_safe():
    state = {}; calls = []
    class Fake:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def cursor(self): return self
        def execute(self, sql, params):
            calls.append(sql)
            if sql.startswith('INSERT'):
                p = params[-1].obj
                if not state: state.update(deepcopy(p)); self.result = (p['output_id'],)
                else: self.result = None
            else: self.result = (state,)
        def fetchone(self): return self.result
    kwargs = dict(host='fictional', port=5432, password='fictional', connect=lambda **kw: Fake())
    with pytest.raises(PermissionError): publish_v3(outputs(), **kwargs)
    assert not calls
    assert publish_v3(outputs(), approved_object=OBJECT, **kwargs)['inserted'] == 1
    assert publish_v3(outputs(), approved_object=OBJECT, **kwargs)['unchanged_existing'] == 1
    state['source_payload_sha256'] = 'b'*64
    with pytest.raises(ValueError): publish_v3(outputs(), approved_object=OBJECT, **kwargs)
    assert all('farm_risk_assessment_v3' in call for call in calls)
