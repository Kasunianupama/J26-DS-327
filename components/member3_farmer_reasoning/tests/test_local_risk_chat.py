"""Synthetic tests for local C4 question routing, dates, truthful answers and API."""
from unittest.mock import Mock
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from components.member3_farmer_reasoning.schemas.tool_contracts import RiskEvidence, ToolOutcome
from components.member3_farmer_reasoning.services import local_risk_chat as chat
from backend.app.api.routes import agent


def outcome(**changes):
    evidence = dict(demo=False, contract_version='1.1.0', score_basis='descriptive_retrospective_unverified',
        scoring_version='synthetic-scoring-v1', model_status='experimental_not_live_validated',
        research_only=True, live_warning_allowed=False, reference_date='2020-01-10',
        assessment_date='2020-01-08', generated_at='2020-02-01T00:00:00Z',
        assessment_count=1, combined_score=25, warnings=['Research only.'])
    evidence.update(changes)
    return ToolOutcome(status='success', tool='c4_risk', message='Synthetic fixture',
                       evidence=RiskEvidence(**evidence))


def router(result=None):
    mock = Mock()
    mock.execute.return_value = result or outcome()
    return mock


def test_historical_question_routes_locally_and_preserves_dates_and_limits():
    tool = router()
    result = chat.answer_local_risk(chat.LocalRiskQuery(query='Show C4 risk assessment for 2020-01-10'), tool)
    assert result['status'] == 'success'
    assert result['cloud_processing'] is False
    assert result['provider'] == 'local_template'
    assert '25.00' in result['answer'] and '2020-01-08' in result['answer']
    assert '2020-02-01' in result['answer']
    assert 'cannot label' in result['answer']
    assert result['evidence']['live_warning_allowed'] is False
    tool.execute.assert_called_once_with(dict(tool='c4_risk', arguments=dict(
        reference_date='2020-01-10', purpose='historical_explanation')))


@pytest.mark.parametrize('question', ['Give a C4 live warning today', 'What is the current risk?', 'C4 alerts now'])
def test_live_requests_do_not_call_database_or_model(question):
    tool = router()
    result = chat.answer_local_risk(chat.LocalRiskQuery(query=question), tool)
    assert result['status'] == 'unavailable'
    tool.execute.assert_not_called()


@pytest.mark.parametrize('question,reference,status', [
    ('Show C4 risk assessment', None, 'needs_input'),
    ('Show C4 for 2020-02-31', None, 'invalid_request'),
    ('Compare C4 on 2020-01-01 and 2020-01-02', None, 'needs_input'),
    ('C4 on 2020-01-08', '2020-01-10', 'needs_input'),
    ('What is the milk forecast?', None, 'unsupported')])
def test_unsupported_or_ambiguous_requests_do_not_execute(question, reference, status):
    tool = router()
    result = chat.answer_local_risk(chat.LocalRiskQuery(query=question, reference_date=reference), tool)
    assert result['status'] == status
    tool.execute.assert_not_called()


def test_reference_picker_supports_missing_date_followup():
    tool = router()
    request = chat.LocalRiskQuery(query='Show the C4 historical assessment', reference_date='2020-01-10')
    assert chat.answer_local_risk(request, tool)['status'] == 'success'


def test_missing_score_not_replaced_and_generation_date_not_backdated():
    result = chat.answer_local_risk(chat.LocalRiskQuery(query='C4 for 2020-01-10'), router(outcome(combined_score=None)))
    assert 'unavailable' in result['answer']
    assert result['evidence']['combined_score'] is None
    assert any('cutoff' in warning for warning in result['warnings'])


def test_synthetic_evidence_is_not_used_in_real_mode():
    result = chat.answer_local_risk(chat.LocalRiskQuery(query='C4 for 2020-01-10'), router(outcome(demo=True)))
    assert result['status'] == 'invalid_result'
    assert 'evidence' not in result


def test_failure_has_no_demo_fallback_or_raw_exception_details():
    tool = router()
    tool.execute.side_effect = RuntimeError('synthetic-private-details')
    result = chat.answer_local_risk(chat.LocalRiskQuery(query='C4 for 2020-01-10'), tool)
    assert result['status'] == 'error'
    assert 'synthetic-private' not in str(result)


def test_local_api_uses_only_local_service(monkeypatch):
    answer = dict(status='needs_input', answer='Choose a date.', provider='local_template',
                  cloud_processing=False, demo=False)
    invoke = Mock(return_value=answer)
    monkeypatch.setattr(agent, 'answer_local_risk', invoke)
    monkeypatch.setattr(agent, 'answer_query', Mock(side_effect=AssertionError('No demo call')))
    app = FastAPI()
    app.include_router(agent.router, prefix='/api/v1')
    response = TestClient(app).post('/api/v1/agent/local-query', json=dict(query='Show C4 assessment'))
    assert response.status_code == 200
    assert response.json() == answer
    assert invoke.call_args.args[0].query == 'Show C4 assessment'


def test_local_api_rejects_injected_provider_or_sql_field():
    app = FastAPI()
    app.include_router(agent.router, prefix='/api/v1')
    response = TestClient(app).post('/api/v1/agent/local-query',
        json=dict(query='Show C4', provider='gemini', sql='anything'))
    assert response.status_code == 422
