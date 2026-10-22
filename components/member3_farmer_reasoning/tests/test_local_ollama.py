"""Local interpretation transport, follow-ups and failure isolation with fictional fixtures."""
import json
from unittest.mock import Mock

import httpx
import pytest

from components.member3_farmer_reasoning.services import local_ollama as runtime
from components.member3_farmer_reasoning.services import language_interpreter as interpreter
from components.member3_farmer_reasoning.services.local_chat import answer_chat, ChatQuery
from components.member3_farmer_reasoning.services.aggregate_brief import build_brief
from components.member3_farmer_reasoning.tests.test_aggregate_brief import context
from components.member3_farmer_reasoning.tests.test_local_chat import forecast_router

PLAN = dict(topic='herd', guard='historical', grain='unspecified', series='unspecified')


def install_transport(monkeypatch, handler):
    original = httpx.Client
    calls = []
    def factory(**kwargs):
        calls.append(kwargs)
        return original(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(runtime.httpx, 'Client', factory)
    return calls


def test_real_client_shape_and_complete_structured_response(monkeypatch):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=dict(done=True, done_reason='stop', message=dict(content=json.dumps(PLAN))))
    calls = install_transport(monkeypatch, handler)
    assert interpreter.qwen_plan('Describe our stock situation').model_dump() == PLAN
    assert len(requests) == 1
    assert str(requests[0].url) == 'http://127.0.0.1:11434/api/chat'
    payload = json.loads(requests[0].content)
    assert payload['keep_alive'] == '5m' and payload['think'] is False
    assert payload['options']['num_predict'] == 120
    assert set(payload) == {'model','stream','think','keep_alive','format','messages','options'}
    assert calls[0]['trust_env'] is False and calls[0]['follow_redirects'] is False


@pytest.mark.parametrize('status,expected', [(404,'model_missing'), (503,'unavailable'), (302,'unavailable')])
def test_http_failure_is_sanitized_and_not_retried(monkeypatch, status, expected):
    handler = Mock(return_value=httpx.Response(status, text='private-diagnostic', headers={'location':'https://example.invalid'}))
    install_transport(monkeypatch, handler)
    with pytest.raises(runtime.OllamaFailure) as caught:
        interpreter.qwen_plan('Fictional question')
    assert caught.value.category == expected
    assert 'private-diagnostic' not in str(caught.value)
    assert handler.call_count == 1


@pytest.mark.parametrize('exception,expected', [(httpx.ReadTimeout('private'),'timeout'), (httpx.ConnectError('private'),'unavailable')])
def test_socket_errors_are_public_categories_only(monkeypatch, exception, expected):
    handler = Mock(side_effect=exception)
    install_transport(monkeypatch, handler)
    with pytest.raises(runtime.OllamaFailure) as caught:
        interpreter.qwen_plan('Fictional question')
    assert caught.value.category == expected and handler.call_count == 1


@pytest.mark.parametrize('body', [
    dict(done=False, message=dict(content=json.dumps(PLAN))),
    dict(done=True, done_reason='length', message=dict(content=json.dumps(PLAN))),
    dict(done=True, done_reason='stop', message=dict(content='reasoning instead of JSON')),
    dict(done=True, done_reason='stop', message=dict(content=json.dumps(dict(PLAN, sql='unapproved')))),
    dict(done=True, done_reason='stop', message=dict(content=json.dumps(dict(PLAN, topic='execute_sql')))),
    dict(done=True, done_reason='stop'),
])
def test_incomplete_or_unapproved_output_is_rejected(monkeypatch, body):
    install_transport(monkeypatch, lambda request: httpx.Response(200, json=body))
    with pytest.raises(runtime.OllamaFailure, match='invalid_response'):
        interpreter.qwen_plan('Fictional question')


@pytest.mark.parametrize('content', [b'not JSON', b'[]', b'x'*65537], ids=['not-json','non-object','oversized'])
def test_bad_or_oversized_response_is_rejected(monkeypatch, content):
    install_transport(monkeypatch, lambda request: httpx.Response(200, content=content))
    with pytest.raises(runtime.OllamaFailure, match='invalid_response'):
        runtime.request_json('POST', '/api/chat')


def test_response_deadline_is_checked_between_chunks(monkeypatch):
    install_transport(monkeypatch, lambda request: httpx.Response(200, json={}))
    moments = iter([0, 24])
    monkeypatch.setattr(runtime, 'monotonic', lambda: next(moments))
    with pytest.raises(runtime.OllamaFailure, match='timeout'):
        runtime.request_json('POST', '/api/chat', timeout=20)


def test_only_allowlisted_loopback_operations_can_run(monkeypatch):
    client = Mock(side_effect=AssertionError('Must not connect'))
    monkeypatch.setattr(runtime.httpx, 'Client', client)
    with pytest.raises(ValueError):
        runtime.request_json('GET', 'https://example.invalid')
    client.assert_not_called()


def test_concurrent_interpretation_is_not_queued_and_failure_releases_lock(monkeypatch):
    request = Mock(side_effect=runtime.OllamaFailure('timeout'))
    monkeypatch.setattr(runtime, 'request_json', request)
    assert runtime._inference.acquire(False)
    try:
        with pytest.raises(runtime.OllamaFailure, match='busy'):
            runtime.classify({})
        request.assert_not_called()
    finally:
        runtime._inference.release()
    for _ in range(2):
        with pytest.raises(runtime.OllamaFailure, match='timeout'):
            runtime.classify({})
    assert request.call_count == 2


def test_readiness_exposes_only_expected_model_metadata(monkeypatch):
    def handler(request):
        body = dict(version='0.test') if request.url.path.endswith('version') else dict(models=[dict(name=runtime.MODEL),dict(name='other-private-local-label')])
        return httpx.Response(200, json=body)
    install_transport(monkeypatch, handler)
    result = runtime.readiness()
    assert result == dict(status='ready', version='0.test', model=runtime.MODEL, model_installed=True, cloud_processing=False)
    assert 'other-private-local-label' not in json.dumps(result)


@pytest.mark.parametrize('payload,status', [(dict(models=[]),'model_missing'), (dict(models=None),'invalid_response')])
def test_readiness_cannot_claim_missing_or_malformed_model_is_ready(monkeypatch, payload, status):
    install_transport(monkeypatch, lambda request: httpx.Response(200, json=dict(version='test') if request.url.path.endswith('version') else payload))
    assert runtime.readiness()['status'] == status


@pytest.mark.parametrize('question', ['Describe our stock situation', 'අපේ තොරතුරු කියන්න', 'எங்களது விபரம் என்ன'])
def test_unfamiliar_wording_in_each_language_uses_validated_local_plan_only(question):
    planner = Mock(return_value=PLAN)
    result = answer_chat(ChatQuery(query=question), language_planner=planner, briefing=lambda:build_brief(context()))
    assert result['status'] == 'success' and result['interpretation_mode'] == 'local_qwen'
    assert result['context']['topic'] == 'herd' and result['cloud_processing'] is False
    planner.assert_called_once_with(question)
    assert 'synthetic-v1' not in str(planner.call_args)


@pytest.mark.parametrize('question', ['Recorded herd summary','සතියේ කිරි','கடந்தகால வானிலை'])
def test_known_wording_does_not_wait_for_qwen(question):
    planner = Mock(side_effect=AssertionError('No model wait'))
    result = answer_chat(ChatQuery(query=question), language_planner=planner, briefing=lambda:build_brief(context()))
    assert result['status'] == 'success' and result['interpretation_mode'] == 'local_rules'
    planner.assert_not_called()


@pytest.mark.parametrize('question,expected', [('and weekly?','weekly'),('what about monthly?','monthly'),('also daily','daily'),('සතිපතා?','weekly'),('வாராந்திர?','weekly')])
def test_explicit_period_followup_preserves_topic_and_requests_correct_dates(question, expected):
    first = answer_chat(ChatQuery(query='Milk forecast'), forecast_router=forecast_router())
    planner = Mock(side_effect=AssertionError('No inference needed'))
    result = answer_chat(ChatQuery(query=question,context=first['context']), language_planner=planner, forecast_router=forecast_router())
    assert result['status'] == 'needs_input'
    assert result['context']['topic'] == 'forecast' and result['context']['grain'] == expected
    assert result['missing_fields'] == ['target_period']
    planner.assert_not_called()


def test_spoken_date_followups_fill_only_the_pending_date_slot():
    first = answer_chat(ChatQuery(query='Milk forecast'), forecast_router=forecast_router())
    second = answer_chat(ChatQuery(query='use 2020-01-02',context=first['context']), forecast_router=forecast_router())
    assert second['status'] == 'success' and second['context']['reference_date'] is None
    third = answer_chat(ChatQuery(query='for 2020-01-03',context=second['context']), forecast_router=forecast_router())
    assert third['status'] == 'success'
    assert third['evidence']['target_period'] == '2020-01-03'


@pytest.mark.parametrize('failure', ['timeout','busy','model_missing','invalid_response','unavailable'])
@pytest.mark.parametrize('language', ['en','si','ta'])
def test_interpretation_failure_is_localized_and_cannot_run_any_tool(failure, language):
    reader=Mock(side_effect=AssertionError('No tool'))
    previous=dict(topic='forecast',reference_date='2020-01-01')
    result=answer_chat(ChatQuery(query='Describe our stock situation',language=language,context=previous),
        language_planner=Mock(side_effect=runtime.OllamaFailure(failure)),
        briefing=reader,forecast_router=reader,risk_router=reader,simulation_invoke=reader)
    assert result['status']=='unsupported' and result['interpretation_failure']==failure
    assert result['context']['topic']=='forecast' and result['context']['reference_date']=='2020-01-01'
    assert result['language']==language and result['cloud_processing'] is False
    assert 'evidence' not in result
    reader.assert_not_called()


@pytest.mark.parametrize('question', ['What is the capital of France?', 'and weekly why did it fall?', 'same date but forecast tomorrow'])
def test_unrelated_or_uncertain_followup_never_inherits_stored_tool_intent(question):
    reader=Mock(side_effect=AssertionError('No tool'))
    planner=Mock(return_value=dict(PLAN,topic='unknown',guard='unknown'))
    result=answer_chat(ChatQuery(query=question,context=dict(topic='herd')),language_planner=planner,briefing=reader)
    assert result['status'] in {'unsupported','needs_input'} and 'evidence' not in result
    reader.assert_not_called()


def test_cli_check_uses_one_fixed_phrase_and_reports_failure_exit(monkeypatch,capsys):
    monkeypatch.setattr(runtime,'readiness',lambda:dict(status='ready',model=runtime.MODEL))
    classify=Mock(side_effect=runtime.OllamaFailure('timeout'))
    monkeypatch.setattr(interpreter,'qwen_plan',classify)
    assert runtime.main(['--check','ta'])==1
    report=json.loads(capsys.readouterr().out)
    assert report['interpretation_status']=='timeout'
    assert len(classify.call_args.args)==1 and classify.call_count==1


def test_module_cli_handles_the_same_failure_class(monkeypatch,capsys):
    import runpy
    import sys
    monkeypatch.setattr(runtime,'readiness',lambda:dict(status='ready',model=runtime.MODEL))
    monkeypatch.setattr(interpreter,'qwen_plan',Mock(side_effect=runtime.OllamaFailure('timeout')))
    monkeypatch.setattr(sys,'argv',['local_ollama','--check','en'])
    with pytest.warns(RuntimeWarning), pytest.raises(SystemExit) as caught:
        runpy.run_module(runtime.__name__,run_name='__main__')
    assert caught.value.code==1
    assert json.loads(capsys.readouterr().out)['interpretation_status']=='timeout'
