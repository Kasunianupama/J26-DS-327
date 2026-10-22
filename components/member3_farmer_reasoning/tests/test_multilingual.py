"""Synthetic parity checks for local Sinhala/Tamil text; no databases or hosted models."""
import json
import re
from unittest.mock import Mock, MagicMock
import pytest
from components.member3_farmer_reasoning.services.local_chat import answer_chat,ChatQuery
from components.member3_farmer_reasoning.services import language_interpreter as interpreter
from components.member3_farmer_reasoning.services.multilingual_answers import translate_warning
from components.member3_farmer_reasoning.services.aggregate_brief import build_brief
from components.member3_farmer_reasoning.tests.test_aggregate_brief import context
from components.member3_farmer_reasoning.tests.test_local_chat import forecast_router
from components.member3_farmer_reasoning.tests.test_c4_repository import router as risk_router


@pytest.mark.parametrize('language,question,topic',[
 ('si','අවසන් රංචු සාරාංශය පෙන්වන්න','herd'),('ta','கடைசி மந்தைச் சுருக்கத்தைக் காட்டுங்கள்','herd'),
 ('si','සතියේ කිරි පෙර සතිය සමඟ සසඳන්න','milk'),('ta','கடைசி வாரத்தின் பாலை முந்தைய வாரத்துடன் ஒப்பிடுங்கள்','milk'),
 ('si','අතීත කාලගුණය සහ THI පෙන්වන්න','weather'),('ta','கடந்தகால வானிலை மற்றும் THI','weather'),
])
def test_native_questions_and_answers_preserve_core_evidence(language,question,topic):
    brief=build_brief(context())
    english=answer_chat(ChatQuery(query={'herd':'Herd summary','milk':'Milk comparison','weather':'Weather THI'}[topic]),briefing=lambda:brief)
    result=answer_chat(ChatQuery(query=question,language=language),briefing=lambda:brief)
    assert result['status']=='success' and result['language']==language
    assert result['evidence']==english['evidence']
    assert result['context']['topic']==topic and result['interpretation_mode']=='local_rules'
    assert re.search('[\u0d80-\u0dff]' if language=='si' else '[\u0b80-\u0bff]',result['answer'])
    assert result['cloud_processing'] is False


@pytest.mark.parametrize('language,question',[('si','දෛනික කිරි පුරෝකථනයක් පෙන්වන්න'),('ta','தினசரி பால் முன்னறிவிப்பைக் காட்டுங்கள்')])
def test_forecast_date_clarifications_and_missing_bounds_preserve_language(language,question):
    first=answer_chat(ChatQuery(query=question,language=language),forecast_router=forecast_router())
    assert first['missing_fields']==['target_period']
    result=answer_chat(ChatQuery(query='2020-01-02',language=language,context=first['context']),forecast_router=forecast_router())
    assert result['status']=='success'
    assert result['evidence']['lower'] is None
    assert result['evidence']['model_version']=='pfoi-1.2.0-dev'
    assert '2020-01-02' in result['answer'] and '2020-01-01' in result['answer']
    assert '100.00' in result['answer']
    assert all(warning!='Development model; source-data compatibility must be established before combining local records.' for warning in result['warnings'])


@pytest.mark.parametrize('language,question',[('si','2020-01-10 අතීත අවදානම් ඇගයීම'),('ta','2020-01-10 கடந்தகால அபாய மதிப்பீடு')])
def test_c4_preserves_research_flags_and_generation_date(language,question):
    result=answer_chat(ChatQuery(query=question,language=language),risk_router=risk_router())
    assert result['status']=='success'
    assert result['evidence']['research_only'] is True
    assert result['evidence']['live_warning_allowed'] is False
    assert result['evidence']['source_core_version'] is None
    assert '2020-02-01' in result['answer'] and '25.00' in result['answer']


@pytest.mark.parametrize('language,question',[
 ('si','අද අවදානම් අනතුරු ඇඟවීම'),('ta','இன்று அபாய எச்சரிக்கை'),
 ('si','හෙට අවදානම කුමක්ද'),('ta','நாளை ஆபத்து என்ன'),
 ('si','කිරි අඩුවීමට හේතුව කුමක්ද'),('ta','பால் குறைந்ததற்கு காரணம் என்ன'),
 ('si','හෙට කාලගුණය කුමක්ද'),('ta','அடுத்த வார வானிலை'),
 ('si','කුමන ගවයන්ට අවධානය අවශ්‍යද'),('ta','எந்த பசுவுக்கு கவனம் தேவை'),
])
def test_native_causal_live_future_and_individual_guards_never_read(language,question):
    reader=Mock(side_effect=AssertionError('No reader'))
    result=answer_chat(ChatQuery(query=question,language=language),briefing=reader,risk_router=reader,forecast_router=reader)
    assert result['status'] in ('unsupported','unavailable')
    assert 'evidence' not in result
    reader.assert_not_called()


def test_unknown_native_wording_can_use_only_a_bounded_injected_local_plan():
    planner=Mock(return_value=dict(topic='herd',guard='historical',grain='unspecified',series='unspecified'))
    result=answer_chat(ChatQuery(query='අපේ තොරතුරු කියන්න',language='si'),language_planner=planner,briefing=lambda:build_brief(context()))
    assert result['status']=='success' and result['interpretation_mode']=='local_qwen'
    planner.assert_called_once_with('අපේ තොරතුරු කියන්න')
    assert 'synthetic-v1' not in str(planner.call_args)


@pytest.mark.parametrize('plan',[
 dict(topic='unknown',guard='unknown',grain='unspecified',series='unspecified'),
 dict(topic='herd',guard='historical',grain='unspecified',series='unspecified',sql='unapproved'),
])
def test_invalid_or_uncertain_local_model_plan_cannot_trigger_a_reader(plan):
    reader=Mock(side_effect=AssertionError('No reader'))
    result=answer_chat(ChatQuery(query='අපේ තොරතුරු කියන්න',language='si'),language_planner=lambda text:plan,briefing=reader)
    assert result['status']=='unsupported' and 'evidence' not in result
    reader.assert_not_called()


def test_unavailable_qwen_fails_locally_without_english_or_synthetic_fallback():
    result=answer_chat(ChatQuery(query='எங்களது விபரம் என்ன',language='ta'),language_planner=Mock(side_effect=TimeoutError()))
    assert result['status']=='unsupported' and result['language']=='ta'
    assert result['cloud_processing'] is False and result['demo'] is False


def test_qwen_client_is_fixed_loopback_and_does_not_receive_evidence(monkeypatch):
    from components.member3_farmer_reasoning.services import local_ollama as runtime
    factory=MagicMock();client=factory.return_value.__enter__.return_value
    reply=client.stream.return_value.__enter__.return_value
    reply.status_code=200
    reply.iter_bytes.return_value=[json.dumps(dict(done=True,done_reason='stop',message=dict(content=json.dumps(dict(topic='herd',guard='historical',grain='unspecified',series='unspecified'))))).encode()]
    monkeypatch.setattr(runtime.httpx,'Client',factory)
    assert interpreter.qwen_plan('Synthetic multilingual input').topic=='herd'
    assert factory.call_args.kwargs['trust_env'] is False
    assert factory.call_args.kwargs['follow_redirects'] is False
    assert client.stream.call_args.args==('POST','http://127.0.0.1:11434/api/chat')
    payload=client.stream.call_args.kwargs['json']
    assert payload['model']=='qwen3:4b-instruct' and payload['think'] is False
    assert payload['messages'][-1]['content']=='Synthetic multilingual input'
    assert set(payload['format']['properties'])=={'topic','guard','grain','series'}


def test_warning_dates_counts_and_incomplete_data_remain_explicit():
    for language in ('si','ta'):
        assert '2020-01-14' in translate_warning('Historical records end on 2020-01-14; these are not current farm conditions.',language)
        assert '69' in translate_warning('69 months fail ETL herd-balance acceptance; herd counts are reconstructed and require review.',language)
    data=context();data['current_period']['delpro_days']=6
    result=answer_chat(ChatQuery(query='සතියේ කිරි',language='si'),briefing=lambda:build_brief(data))
    assert result['evidence']['milk']['delpro']['change_pct'] is None
    assert '6' in result['answer']


def test_invalid_language_is_rejected():
    with pytest.raises(ValueError):ChatQuery(query='Herd',language='fr')


@pytest.mark.parametrize('question',['why කිරි අඩුයි','பால் tomorrow','individual ගවයන්','risk අද'])
def test_mixed_language_guards_are_not_lost(question):
    reader=Mock(side_effect=AssertionError('No reader'))
    result=answer_chat(ChatQuery(query=question,language='ta'),briefing=reader,risk_router=reader)
    assert result['status'] in ('unsupported','unavailable')
    reader.assert_not_called()


@pytest.mark.parametrize('question,grain',[('සතිපතා','weekly'),('வாராந்திர','weekly'),('මාසික','monthly'),('தினசரி','daily')])
def test_native_period_followups_do_not_require_qwen(question,grain):
    planner=Mock(side_effect=AssertionError('No inference required'))
    canonical,mode=interpreter.normalize_question(question,planner=planner)
    assert canonical==grain and mode=='local_rules'
    planner.assert_not_called()
