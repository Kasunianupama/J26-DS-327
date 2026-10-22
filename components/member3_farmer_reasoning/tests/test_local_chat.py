"""Synthetic unified-chat tests: privacy, clarification, routing and source integrity."""
from datetime import date
from unittest.mock import Mock, MagicMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from components.member3_farmer_reasoning.services import local_chat as chat
from components.member3_farmer_reasoning.services import c1_repository as c1
from components.member3_farmer_reasoning.schemas.tool_contracts import ForecastArguments
from components.member3_farmer_reasoning.orchestration.tool_router import ToolRouter, Adapter
from components.member3_farmer_reasoning.services.aggregate_brief import build_brief
from components.member3_farmer_reasoning.tests.test_aggregate_brief import context
from components.member3_farmer_reasoning.tests.test_c4_repository import router as risk_router


def ask(query, **kwargs):
    return chat.ChatQuery(query=query, **kwargs)


def test_incomplete_milk_coverage_does_not_create_weekly_change():
    data = context()
    data['current_period']['delpro_days'] = 6
    result = chat.answer_chat(ask('Compare recorded milk weeks'), briefing=lambda: build_brief(data))
    assert result['status'] == 'success'
    assert result['demo'] is False and result['cloud_processing'] is False
    assert '6 of 7' in result['answer']
    assert 'cannot be calculated' in result['answer']
    assert result['evidence']['milk']['delpro']['change_pct'] is None
    assert 'Sources remain separate' in result['answer']


def test_herd_is_historical_and_preserves_reconstruction_warning():
    result = chat.answer_chat(ask('Show the herd summary'), briefing=lambda: build_brief(context()))
    assert result['status'] == 'success'
    assert '2020-01-14' in result['answer'] and 'historical reconstructed' in result['answer']
    assert any('balance' in warning for warning in result['warnings'])


def test_weather_does_not_infer_forecast_or_cause():
    result = chat.answer_chat(ask('Show historical THI'), briefing=lambda: build_brief(context()))
    assert result['status'] == 'success'
    assert 'reanalysis' in result['answer'] and 'not supplied' in result['answer']


def test_wrong_core_date_does_not_answer_with_latest_snapshot():
    result = chat.answer_chat(ask('Herd on 2019-01-01'), briefing=lambda: build_brief(context()))
    assert result['status'] == 'unavailable' and 'evidence' not in result


def test_forecast_only_asks_for_the_farmers_target_date_before_reading():
    router = Mock()
    first = chat.answer_chat(ask('Show a weekly milk forecast'), forecast_router=router)
    assert first['missing_fields'] == ['target_period']
    assert first['context']['grain'] == 'weekly'
    assert first['context']['reference_date'] is None
    assert 'reference date' not in first['answer'].lower()
    router.execute.assert_not_called()


def forecast_router(**updates):
    def invoke(args):
        result = dict(kind='c1_forecast', demo=False, core_version='synthetic-other-core',
            model_version=args.model_version, origin_date=date(2020, 1, 1),
            target_period=args.target_period, grain=args.grain, series=args.series,
            forecast=100, lower=None, upper=None, quality_flags=['synthetic-test'])
        result.update(updates)
        return result
    return ToolRouter(dict(c1_forecast=Adapter(invoke, False)))


def test_forecast_preserves_development_missing_bounds_and_source_version():
    result = chat.answer_chat(ask('Milk forecast', reference_date='2020-01-01', target_period='2020-01-02'), forecast_router=forecast_router())
    assert result['status'] == 'success'
    assert result['evidence']['model_version'] == 'pfoi-1.2.0-dev'
    assert result['evidence']['core_version'] == 'synthetic-other-core'
    assert 'incomplete' in result['answer'] and 'unverified' in result['answer']
    assert 'guaranteed' in result['answer']


def test_forecast_rejects_synthetic_adapter_mismatch():
    result = chat.answer_chat(ask('Milk forecast', reference_date='2020-01-01', target_period='2020-01-02'), forecast_router=forecast_router(demo=True))
    assert result['status'] == 'unavailable' and 'evidence' not in result


def test_risk_date_followup_retains_research_flags():
    first = chat.answer_chat(ask('Historical risk assessment'), risk_router=risk_router())
    assert first['missing_fields'] == ['reference_date']
    result = chat.answer_chat(ask('2020-01-10', context=first['context']), risk_router=risk_router())
    assert result['status'] == 'success'
    assert result['evidence']['research_only'] is True
    assert result['evidence']['live_warning_allowed'] is False


@pytest.mark.parametrize('question', ['Risk warning today', 'Run a feed simulation', 'Why did milk fall?', 'What is the capital of France?'])
def test_unsupported_live_causal_simulation_requests_never_read(question):
    reader = Mock(side_effect=AssertionError('No reader'))
    result = chat.answer_chat(ask(question), briefing=reader, risk_router=reader, forecast_router=reader)
    assert result['status'] in ('unavailable', 'unsupported')
    assert 'evidence' not in result
    reader.assert_not_called()


@pytest.mark.parametrize('question', ['risk on 2020-02-30', 'risk between 2020-01-01 and 2020-01-02'])
def test_invalid_ambiguous_dates_do_not_invoke_readers(question):
    router = Mock()
    result = chat.answer_chat(ask(question), risk_router=router)
    assert result['status'] in ('invalid_request', 'needs_input')
    router.execute.assert_not_called()


def test_failed_reader_does_not_expose_private_diagnostic():
    reader = Mock(side_effect=RuntimeError('private-diagnostic'))
    result = chat.answer_chat(ask('Herd summary'), briefing=reader)
    assert result['status'] == 'unavailable'
    assert 'private-diagnostic' not in str(result)


def test_new_topic_does_not_reuse_forecast_target_as_risk_date():
    result = chat.answer_chat(ask('Historical risk', context=dict(topic='forecast', target_period='2020-01-02')))
    assert result['missing_fields'] == ['reference_date']
    assert result['context']['target_period'] is None


def test_api_routes_real_chat_without_using_demo(monkeypatch):
    from backend.app.api.routes import agent
    monkeypatch.setattr(agent, 'answer_chat', lambda request: dict(status='needs_input', demo=False, cloud_processing=False))
    monkeypatch.setattr(agent, 'answer_query', Mock(side_effect=AssertionError('No demo')))
    app = FastAPI()
    app.include_router(agent.router)
    client = TestClient(app)
    assert client.post('/agent/chat', json=dict(query='Risk')).json()['demo'] is False
    assert client.post('/agent/chat', json=dict(query=' ', model_path='unapproved')).status_code == 422


def test_c1_reader_queries_aggregate_unique_forecast_read_only(monkeypatch):
    connect = MagicMock()
    monkeypatch.setattr(c1.psycopg, 'connect', connect)
    cursor = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = dict(forecast_count=1, version_count=1,
        core_version='synthetic-core', origin_date=date(2020, 1, 1),
        forecast=100, lower=None, upper=None, quality_flags=None)
    args = ForecastArguments(reference_date='2020-01-01', target_period='2020-01-02', grain='daily', series='herd_milk')
    result = c1.read_forecast(args, settings={})
    assert result['quality_flags'] == [] and result['forecast'] == 100
    assert 'READ ONLY' in cursor.execute.call_args_list[0].args[0]
    assert cursor.execute.call_args_list[1].args[1]['model_version'] == 'pfoi-1.2.0-dev'
    assert 'origin_date <= %(reference_date)s' in c1.FORECAST_SQL


@pytest.mark.parametrize('count,versions', [(0, 0), (2, 1), (1, 0)])
def test_c1_reader_rejects_missing_duplicate_or_unknown_provenance(monkeypatch, count, versions):
    connect = MagicMock()
    monkeypatch.setattr(c1.psycopg, 'connect', connect)
    cursor = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = dict(forecast_count=count, version_count=versions)
    args = ForecastArguments(reference_date='2020-01-01', target_period='2020-01-02', grain='daily', series='herd_milk')
    with pytest.raises(ValueError):
        c1.read_forecast(args, settings={})


@pytest.mark.parametrize('question', ['Which cows need attention?', 'Milk production tomorrow', 'Weather next week'])
def test_individual_and_future_questions_never_masquerade_as_recorded_summary(question):
    reader = Mock(side_effect=AssertionError('No read'))
    result = chat.answer_chat(ask(question), briefing=reader)
    assert result['status'] == 'unsupported'
    reader.assert_not_called()


def test_target_only_question_selects_stored_forecast_without_reference_prompt():
    router=Mock(wraps=forecast_router())
    result=chat.answer_chat(ask('Daily milk forecast for 2020-01-02'),forecast_router=router)
    assert result['status']=='success' and result['evidence']['origin_date']=='2020-01-01'
    assert router.execute.call_args.args[0]['arguments']['reference_date']==date(2020,1,2)
    assert result['context']['reference_date'] is None
    assert result['evidence']['model_version']=='pfoi-1.2.0-dev'


def test_automatic_cutoff_changes_with_target_and_is_never_after_today(monkeypatch):
    class FrozenDate(date):
        @classmethod
        def today(cls):return date(2020,1,10)
    monkeypatch.setattr(chat,'date',FrozenDate)
    router=Mock(wraps=forecast_router())
    first=chat.answer_chat(ask('Milk forecast for 2020-01-02'),forecast_router=router)
    second=chat.answer_chat(ask('2020-01-03',context=first['context']),forecast_router=router)
    future=chat.answer_chat(ask('Milk forecast for 2040-01-01',context=second['context']),forecast_router=router)
    cutoffs=[item.args[0]['arguments']['reference_date'] for item in router.execute.call_args_list]
    assert cutoffs==[date(2020,1,2),date(2020,1,3),date(2020,1,10)]
    assert future['context']['reference_date'] is None


def test_explicit_historical_cutoff_is_preserved_in_advanced_use():
    router=Mock(wraps=forecast_router())
    result=chat.answer_chat(ask('Milk forecast for 2020-01-04',reference_date='2020-01-02'),forecast_router=router)
    assert result['status']=='success'
    assert router.execute.call_args.args[0]['arguments']['reference_date']==date(2020,1,2)
    assert result['context']['reference_date']=='2020-01-02'


def test_automatic_selection_does_not_fallback_to_another_model_or_fake_value():
    router=Mock(wraps=forecast_router(model_version='unapproved-model'))
    result=chat.answer_chat(ask('Milk forecast for 2020-01-02'),forecast_router=router)
    assert result['status']=='unavailable' and 'evidence' not in result
    assert router.execute.call_count==1
