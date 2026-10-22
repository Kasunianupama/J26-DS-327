"""Synthetic natural-language C2 execution and clarification tests; no live tools or farm data."""
from unittest.mock import Mock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from components.member3_farmer_reasoning.services.local_chat import ChatQuery, answer_chat
from components.member3_farmer_reasoning.services import c2_gateway
from components.member3_farmer_reasoning.services.c2_dialogue import extract
from components.member3_farmer_reasoning.tests.test_c2_bridge import payload


def invoke_fixture(args):return payload(args)


@pytest.mark.parametrize('language,question,thi,milkings',[
 ('en','What happens if THI drops to 68 for cow A_SYNTHETIC_1?',68,None),
 ('en','If I milk A_SYNTHETIC_1 three times a day, what would milk yield be?',None,3),
 ('en','What if A_SYNTHETIC_1 has THI 68 and 3 milkings per day?',68,3),
 ('en','Simulate THI from 70 to 68 for A_SYNTHETIC_1',68,None),
 ('si','A_SYNTHETIC_1 සඳහා THI අගය 68 කළොත් කිරි කීයද?',68,None),
 ('ta','A_SYNTHETIC_1 க்கு THIஐ 68ஆக குறைத்தால் பாலின் அளவு என்ன?',68,None),
 ('ta','A_SYNTHETIC_1 தினமும் மூன்று முறை கறந்தால் என்ன ஆகும்?',None,3),
])
def test_complete_natural_question_runs_c2_once_without_manual_fields(language,question,thi,milkings):
    invoke=Mock(side_effect=invoke_fixture)
    result=answer_chat(ChatQuery(query=question,language=language),simulation_invoke=invoke)
    assert result['status']=='success' and result['tool']=='c2_simulation'
    invoke.assert_called_once()
    args=invoke.call_args.args[0]
    assert args.animal_ref=='A_SYNTHETIC_1' and args.thi_mean==thi and args.milkings_per_day==milkings
    assert result['context']['awaiting'] is None and result['language']==language
    assert 'action' not in result and 'Run what-if' not in result['answer']
    assert result['cloud_processing'] is False and result['demo'] is False


def test_general_question_explains_scope_and_optional_reference_runs_c2_internally():
    invoke=Mock(side_effect=invoke_fixture)
    first=answer_chat(ChatQuery(query='What if THI is 68?'),simulation_invoke=invoke)
    assert first['status']=='information' and first['context']['awaiting'] is None
    assert first['context']['scenario']['thi_mean']==68
    invoke.assert_not_called()
    second=answer_chat(ChatQuery(query='A_SYNTHETIC_1',context=first['context']),simulation_invoke=invoke)
    assert second['status']=='success';invoke.assert_called_once()
    assert second['evidence']['proposed_inputs']==dict(thi_mean=68)


@pytest.mark.parametrize('language,question,answer',[
 ('en','Run a THI what-if for A_SYNTHETIC_1','68'),
 ('si','A_SYNTHETIC_1 සඳහා THI අනුකරණයක් කරන්න','68'),
 ('ta','A_SYNTHETIC_1 க்கு THI மாற்றத்தை உருவகப்படுத்துங்கள்','௬௮'),
])
def test_missing_absolute_value_uses_next_chat_turn_without_a_model_guess(language,question,answer):
    invoke=Mock(side_effect=invoke_fixture)
    first=answer_chat(ChatQuery(query=question,language=language),simulation_invoke=invoke)
    assert first['context']['awaiting']=='simulation_thi';invoke.assert_not_called()
    result=answer_chat(ChatQuery(query=answer,language=language,context=first['context']),simulation_invoke=invoke)
    assert result['status']=='success';assert invoke.call_args.args[0].thi_mean==68
    assert result['language']==language


def test_combined_scenario_accumulates_details_and_runs_only_after_the_last_answer():
    invoke=Mock(side_effect=invoke_fixture)
    first=answer_chat(ChatQuery(query='Simulate THI and milking frequency for A_SYNTHETIC_1'),simulation_invoke=invoke)
    assert first['context']['awaiting']=='simulation_thi'
    second=answer_chat(ChatQuery(query='68',context=first['context']),simulation_invoke=invoke)
    assert second['context']['awaiting']=='simulation_milkings';invoke.assert_not_called()
    third=answer_chat(ChatQuery(query='three',context=second['context']),simulation_invoke=invoke)
    assert third['status']=='success';invoke.assert_called_once()
    assert invoke.call_args.args[0].producer_request()['combined_scenario']['milkings_per_day']==3


def test_new_feature_does_not_silently_keep_an_old_combined_alternative():
    first=answer_chat(ChatQuery(query='What if A_SYNTHETIC_1 has THI 68 and milkings 3?'),simulation_invoke=invoke_fixture)
    invoke=Mock(side_effect=invoke_fixture)
    second=answer_chat(ChatQuery(query='What if THI is 69 instead?',context=first['context']),simulation_invoke=invoke)
    assert second['status']=='success';args=invoke.call_args.args[0]
    assert args.animal_ref=='A_SYNTHETIC_1' and args.thi_mean==69 and args.milkings_per_day is None


def test_and_followup_adds_an_explicit_feature_for_the_same_cow():
    first=answer_chat(ChatQuery(query='What if A_SYNTHETIC_1 has THI 68?'),simulation_invoke=invoke_fixture)
    invoke=Mock(side_effect=invoke_fixture)
    second=answer_chat(ChatQuery(query='And 3 milkings per day',context=first['context']),simulation_invoke=invoke)
    assert second['status']=='success'
    assert invoke.call_args.args[0].thi_mean==68 and invoke.call_args.args[0].milkings_per_day==3


@pytest.mark.parametrize('question',[
 'What if THI decreases by 2 for A_SYNTHETIC_1?',
 'What if THI changes by 10% for A_SYNTHETIC_1?',
 'What if THI is 68 or 70 for A_SYNTHETIC_1?',
 'What if THI 68 for A_SYNTHETIC_1 and A_SYNTHETIC_2?',
 'What if milkings are 0 for A_SYNTHETIC_1?',
 'What if THI is from 70 for A_SYNTHETIC_1?',
])
def test_relative_ambiguous_multiple_cow_and_invalid_values_never_run_c2(question):
    invoke=Mock(side_effect=AssertionError('No tool call'))
    result=answer_chat(ChatQuery(query=question),simulation_invoke=invoke)
    assert result['status']=='needs_input';invoke.assert_not_called()


def test_relative_revision_clears_previous_target_and_does_not_reexecute_stale_inputs():
    first=answer_chat(ChatQuery(query='What if THI 68 for A_SYNTHETIC_1?'),simulation_invoke=invoke_fixture)
    invoke=Mock(side_effect=AssertionError('No old scenario'))
    revised=answer_chat(ChatQuery(query='Decrease THI by 2',context=first['context']),simulation_invoke=invoke)
    assert revised['status']=='needs_input' and revised['context']['scenario']['thi_mean'] is None
    invoke.assert_not_called()


def test_decimal_followup_keeps_its_leading_decimal_point():
    first=answer_chat(ChatQuery(query='What if milkings for A_SYNTHETIC_1?'),simulation_invoke=invoke_fixture)
    invoke=Mock(side_effect=invoke_fixture)
    result=answer_chat(ChatQuery(query='.5',context=first['context']),simulation_invoke=invoke)
    assert result['status']=='success' and invoke.call_args.args[0].milkings_per_day==.5


@pytest.mark.parametrize('question',[
 'Simulate a feed increase for A_SYNTHETIC_1',
 'Why would THI 68 cause a cure in this what-if for A_SYNTHETIC_1?',
 'What if THI 68 for all cows?',
 'What if THI 68 for A_SYNTHETIC_1 over 7 days?',
 'What if THI 68 for A_SYNTHETIC_1 for two days?',
 'What if THI 68 for A_SYNTHETIC_1 on 2020-01-01?',
 'Do not run a THI 68 simulation for A_SYNTHETIC_1',
])
def test_unsupported_scope_horizon_and_cancelled_questions_do_not_call_c2(question):
    invoke=Mock(side_effect=AssertionError('No call'))
    result=answer_chat(ChatQuery(query=question),simulation_invoke=invoke)
    assert result['status'] in ('unsupported','cancelled');invoke.assert_not_called()


def test_cancel_and_unrelated_questions_do_not_inherit_a_pending_execution():
    first=answer_chat(ChatQuery(query='What if THI 68?'),simulation_invoke=invoke_fixture)
    invoke=Mock(side_effect=AssertionError('No call'))
    cancelled=answer_chat(ChatQuery(query='cancel',context=first['context']),simulation_invoke=invoke)
    assert cancelled['status']=='cancelled' and cancelled['context']['scenario'] is None
    unrelated=answer_chat(ChatQuery(query='What is the capital of France?',context=first['context']),simulation_invoke=invoke)
    assert unrelated['status']=='unsupported';invoke.assert_not_called()


def test_reference_digits_are_not_treated_as_proposed_thi():
    result=answer_chat(ChatQuery(query='What if THI for A_SYNTHETIC_68?'),simulation_invoke=Mock(side_effect=AssertionError('No inferred number')))
    assert result['status']=='needs_input' and result['context']['scenario']['thi_mean'] is None


def test_question_only_api_request_reaches_c2_without_a_structured_manual_payload(monkeypatch):
    from backend.app.api.routes import agent
    invoke=Mock(side_effect=invoke_fixture);monkeypatch.setattr(c2_gateway,'call_c2',invoke)
    app=FastAPI();app.include_router(agent.router);client=TestClient(app)
    result=client.post('/agent/chat',json=dict(query='What if THI 68 for A_SYNTHETIC_1?',language='en'))
    assert result.status_code==200 and result.json()['status']=='success';invoke.assert_called_once()
    assert 'action' not in result.json()


def test_client_context_cannot_supply_a_model_path_or_tool_endpoint():
    with pytest.raises(ValueError):
        ChatQuery(query='68',context=dict(topic='simulation',scenario=dict(animal_ref='A_SYNTHETIC_1',model_path='unapproved')))


def test_relative_question_without_a_cow_accepts_the_value_requested_by_its_prompt():
    first=answer_chat(ChatQuery(query='What if THI decreases by 2?'),simulation_invoke=invoke_fixture)
    assert first['simulation_state']=='general' and first['context']['awaiting'] is None
    invoke=Mock(side_effect=invoke_fixture)
    second=answer_chat(ChatQuery(query='THI 68',context=first['context']),simulation_invoke=invoke)
    assert second['simulation_state']=='general' and second['context']['scenario']['thi_mean']==68
    invoke.assert_not_called()
    third=answer_chat(ChatQuery(query='A_SYNTHETIC_1',context=second['context']),simulation_invoke=invoke)
    assert third['status']=='success';invoke.assert_called_once()


def test_thanks_after_a_completed_scenario_does_not_run_c2_again():
    first=answer_chat(ChatQuery(query='What if THI 68 for A_SYNTHETIC_1?'),simulation_invoke=invoke_fixture)
    invoke=Mock(side_effect=AssertionError('No repeat'))
    result=answer_chat(ChatQuery(query='thanks',context=first['context']),simulation_invoke=invoke)
    assert result['status']=='unsupported';invoke.assert_not_called()


def test_a_new_question_without_a_target_does_not_reuse_the_previous_target():
    first=answer_chat(ChatQuery(query='What if THI 68 for A_SYNTHETIC_1?'),simulation_invoke=invoke_fixture)
    invoke=Mock(side_effect=AssertionError('No repeat'))
    result=answer_chat(ChatQuery(query='What if THI?',context=first['context']),simulation_invoke=invoke)
    assert result['status']=='needs_input' and result['context']['scenario']['thi_mean'] is None
    invoke.assert_not_called()


def test_tamil_word_for_model_is_not_misread_as_a_monthly_horizon():
    result=answer_chat(ChatQuery(query='இந்த மாதிரியில் A_SYNTHETIC_1 க்கு THI 68 குறைத்தால்?',language='ta'),simulation_invoke=invoke_fixture)
    assert result['status']=='success'


@pytest.mark.parametrize('reference',['cow 2','cow UNKNOWN','cow a_other'])
def test_unrecognised_new_cow_never_reuses_the_previous_cow(reference):
    first=answer_chat(ChatQuery(query='What if THI 68 for A_SYNTHETIC_1?'),simulation_invoke=invoke_fixture)
    invoke=Mock(side_effect=AssertionError('No previous cow'))
    result=answer_chat(ChatQuery(query='What if THI 69 for '+reference+'?',context=first['context']),simulation_invoke=invoke)
    assert result['status']=='needs_input' and result['context']['scenario']['animal_ref'] is None
    invoke.assert_not_called()


def test_cancel_command_also_clears_complete_scenario_context():
    first=answer_chat(ChatQuery(query='What if THI 68 for A_SYNTHETIC_1?'),simulation_invoke=invoke_fixture)
    invoke=Mock(side_effect=AssertionError('No repeat'))
    result=answer_chat(ChatQuery(query='do not run',context=first['context']),simulation_invoke=invoke)
    assert result['status']=='cancelled' and result['context']['scenario'] is None
    invoke.assert_not_called()
