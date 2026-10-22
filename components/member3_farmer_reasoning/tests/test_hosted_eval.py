"""Mocked hosted-evaluation tests; no keys, environment files, farm data or network."""
import json
from unittest.mock import Mock
import httpx
import pytest
from components.member3_farmer_reasoning.orchestration import hosted_eval as evaluation


def case(name):
    return next(c for c in evaluation.CASES if c['id'] == name)


def response(text):
    return httpx.Response(200, request=httpx.Request('POST', 'https://example.invalid'),
        json=dict(candidates=[dict(finishReason='STOP', content=dict(parts=[dict(text=text)]))],
                  usageMetadata=dict(totalTokenCount=12)))


def test_default_preview_never_loads_settings_or_opens_network(monkeypatch, capsys):
    import dotenv
    fail = Mock(side_effect=AssertionError('No settings/network'))
    monkeypatch.setattr(dotenv, 'dotenv_values', fail)
    monkeypatch.setattr(httpx, 'Client', fail)
    assert evaluation.main([]) == 0
    assert json.loads(capsys.readouterr().out)['requests'] == 0
    fail.assert_not_called()


def test_explicit_live_requires_model_before_reading_credentials():
    with pytest.raises(SystemExit):
        evaluation.main(['--live'])


def test_fixed_endpoint_receives_only_fixture_and_key_header():
    client = Mock()
    client.post.return_value = response('{"answer":"6 of 7 days recorded."}')
    text, elapsed, usage = evaluation.generate(client, 'synthetic-model', 'synthetic-secret', case('explain_en'))
    url = client.post.call_args.args[0]
    kwargs = client.post.call_args.kwargs
    assert url == 'https://generativelanguage.googleapis.com/v1beta/models/synthetic-model:generateContent'
    assert kwargs['headers']['x-goog-api-key'] == 'synthetic-secret'
    assert 'synthetic-secret' not in json.dumps(kwargs['json'])
    assert 'fictional farm' in json.dumps(kwargs['json'])
    assert elapsed >= 0 and usage['totalTokenCount'] == 12


@pytest.mark.parametrize('model', ['../elsewhere', 'https://example.invalid', 'models/other'])
def test_arbitrary_model_paths_do_not_trigger_requests(model):
    client = Mock()
    with pytest.raises(evaluation.EvaluationError):
        evaluation.generate(client, model, 'synthetic', case('explain_en'))
    client.post.assert_not_called()


def test_api_failure_never_prints_provider_body_or_key():
    client = Mock()
    client.post.return_value = httpx.Response(401,
        request=httpx.Request('POST', 'https://example.invalid'), text='synthetic-private-diagnostic')
    with pytest.raises(evaluation.EvaluationError) as error:
        evaluation.generate(client, 'synthetic-model', 'synthetic-secret', case('explain_en'))
    assert '401' in str(error.value)
    assert 'synthetic-private' not in str(error.value)
    assert 'synthetic-secret' not in str(error.value)


def test_truncated_response_is_not_scored_as_final_answer():
    client = Mock()
    client.post.return_value = httpx.Response(200, request=httpx.Request('POST', 'https://example.invalid'),
        json=dict(candidates=[dict(finishReason='MAX_TOKENS')]))
    with pytest.raises(evaluation.EvaluationError):
        evaluation.generate(client, 'synthetic-model', 'synthetic-secret', case('explain_en'))


def test_language_script_check_does_not_claim_semantic_accuracy():
    result = evaluation.assess(case('explain_ta'), '{"answer":"This has 6 of 7 days."}')
    assert result['script_matches'] is False
    assert result['human_review_required'] is True
    assert result['supplied_digits_preserved'] is True


def test_fabricated_digits_are_flagged():
    result = evaluation.assess(case('explain_en'), '{"answer":"6 of 7 days; 500 litres missing."}')
    assert result['unexpected_digits'] == ['500']


def test_malformed_json_not_accepted():
    assert evaluation.assess(case('explain_en'), 'Not JSON')['format_ok'] is False


def test_tool_selection_is_validated_against_synthetic_router():
    text = '{"tool":"core_summary","arguments":{"topic":"herd"}}'
    result = evaluation.assess(case('route_core_en'), text)
    assert result['routing_matches'] is True
    assert result['synthetic_tools_only'] is True


def test_missing_simulation_horizon_is_clarified_not_defaulted():
    text = '{"tool":"c2_simulation","arguments":{"intervention":"feed","change_percent":10}}'
    result = evaluation.assess(case('route_simulation_ta'), text)
    assert result['routing_matches'] is True
    assert result['missing_fields'] == ['horizon_days']


def test_hallucinated_tool_name_is_rejected():
    result = evaluation.assess(case('route_core_en'), '{"tool":"run_sql","arguments":{}}')
    assert result['format_ok'] is False


def test_wrong_core_topic_is_not_a_successful_route():
    result = evaluation.assess(case('route_core_en'), '{"tool":"core_summary","arguments":{"topic":"weather"}}')
    assert result['routing_matches'] is False


def test_wrong_forecast_dates_are_not_a_successful_route():
    text = json.dumps(dict(tool='c1_forecast', arguments=dict(reference_date='2021-01-01',
        target_period='2021-01-02', grain='daily', series='herd_milk')))
    assert evaluation.assess(case('route_forecast_si'), text)['routing_matches'] is False


@pytest.mark.parametrize('error,category', [
    (httpx.ReadTimeout('synthetic-private-timeout'), 'timeout'),
    (httpx.ConnectError('synthetic-private-connection'), 'connection'),
    (httpx.ConnectError('certificate verify failed: synthetic-private'), 'tls'),
    (httpx.RemoteProtocolError('synthetic-private-protocol'), 'transport'),
])
def test_transport_failures_are_distinguishable_and_sanitized(error, category):
    client = Mock()
    client.post.side_effect = error
    with pytest.raises(evaluation.EvaluationError) as failure:
        evaluation.generate(client, 'synthetic-model', 'synthetic-secret', case('explain_en'))
    assert failure.value.category == category
    assert 'synthetic-private' not in str(failure.value)
    assert 'synthetic-secret' not in str(failure.value)


@pytest.mark.parametrize('payload,category', [
    ({'promptFeedback': {'blockReason': 'SAFETY'}}, 'provider_blocked'),
    ({'candidates': []}, 'response_shape'),
    ({'candidates': [{'finishReason': 'MAX_TOKENS'}]}, 'output_limit'),
    ({'candidates': [{'finishReason': 'STOP', 'content': {'parts': []}}]}, 'empty_answer'),
])
def test_response_categories_do_not_expose_content(payload, category):
    client = Mock()
    client.post.return_value = httpx.Response(200,
        request=httpx.Request('POST', 'https://example.invalid'), json=payload)
    with pytest.raises(evaluation.EvaluationError) as failure:
        evaluation.generate(client, 'synthetic-model', 'synthetic-secret', case('explain_en'))
    assert failure.value.category == category


def test_non_json_response_reports_format_error_without_body():
    client = Mock()
    client.post.return_value = httpx.Response(200,
        request=httpx.Request('POST', 'https://example.invalid'), text='synthetic-private-html')
    with pytest.raises(evaluation.EvaluationError) as failure:
        evaluation.generate(client, 'synthetic-model', 'synthetic-secret', case('explain_en'))
    assert failure.value.category == 'response_format'
    assert 'synthetic-private' not in str(failure.value)


def test_explanation_requests_constrain_the_answer_envelope():
    schema = evaluation.response_schema(case('explain_en'))
    assert schema['required'] == ['answer']
    assert set(schema['properties']) == {'answer'}
    assert schema['additionalProperties'] is False


def test_routing_schema_preserves_missing_inputs_for_clarification():
    schema = evaluation.response_schema(case('route_simulation_ta'))
    assert schema['required'] == ['tool', 'arguments']
    assert set(schema['properties']['tool']['enum']) == {'core_summary', 'c1_forecast', 'c2_simulation'}
    arguments = schema['properties']['arguments']
    assert 'horizon_days' in arguments['properties']
    assert 'horizon_days' not in arguments.get('required', [])
    assert arguments['additionalProperties'] is False


def test_generated_request_includes_schema_not_only_json_mode():
    client = Mock()
    client.post.return_value = response('{"tool":"core_summary","arguments":{"topic":"herd"}}')
    evaluation.generate(client, 'synthetic-model', 'synthetic-secret', case('route_core_en'))
    config = client.post.call_args.kwargs['json']['generationConfig']
    assert config['responseJsonSchema'] == evaluation.response_schema(case('route_core_en'))
    assert config['responseMimeType'] == 'application/json'


def test_wrong_envelope_is_still_rejected_without_silent_normalization():
    result = evaluation.assess(case('route_core_en'), '{"name":"core_summary","parameters":{"topic":"herd"}}')
    assert result['format_ok'] is False
    assert result['error_category'] == 'tool_contract'
