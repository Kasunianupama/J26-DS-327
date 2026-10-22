"""Synthetic C3/C2 contract, privacy and failure checks; no real API, model or database."""
import copy
import json
from unittest.mock import Mock, MagicMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from components.member3_farmer_reasoning.services import c2_gateway as gateway
from components.member3_farmer_reasoning.services.local_chat import ChatQuery, answer_chat


def request(**updates):
    return gateway.ScenarioInput.model_validate(dict(animal_ref='A_SYNTHETIC_1',thi_mean=68,**updates))


def payload(args=None):
    args=args or request();body=args.producer_request()
    common=dict(scenario_status='ESTIMATED_MODEL_INPUT_PERTURBATION',model_support_status='PASSED',
        baseline_predicted_milk_yield_l_day=20,counterfactual_predicted_milk_yield_l_day=22,
        absolute_yield_change_l_day=2,percentage_yield_change=10,model_version='synthetic-model-v1',
        assumptions=['Fictional fixed features'],data_limitations=['Fictional limitation'],warnings=['Fictional warning'])
    result=dict(contract_version='1.1',animal_ref=args.animal_ref,observed_date='2020-01-10',
        observed_milk_yield_l_day=18,prediction_horizon_days=1,baseline_status='AVAILABLE',
        baseline_predicted_milk_yield_l_day=20,model_version='synthetic-model-v1',
        scenarios=[],combined_scenario=None,warnings=['Synthetic-only fixture'],
        cow_state=dict(private_test_field='must-not-copy-cow-state'))
    if 'combined_scenario' in body:
        result['combined_scenario']=dict(**common,**body['combined_scenario'],
            baseline_thi_mean=70,proposed_thi_mean=args.thi_mean,
            baseline_milkings_per_day=2,proposed_milkings_per_day=args.milkings_per_day)
    else:
        result['scenarios']=[dict(**common,**body['scenarios'][0],baseline_value=70 if args.thi_mean is not None else 2)]
    return result


@pytest.mark.parametrize('fields',[
 dict(animal_ref='A_SYNTHETIC_1',thi_mean=68),
 dict(animal_ref='A_SYNTHETIC_1',milkings_per_day=3),
 dict(animal_ref='A_SYNTHETIC_1',thi_mean=68,milkings_per_day=3),
])
def test_absolute_inputs_match_the_documented_single_or_combined_api(fields):
    args=gateway.ScenarioInput(**fields);body=args.producer_request()
    assert body['prediction_horizon_days']==1
    from components.member1_didt.schemas.counterfactual import SimulationRequest
    SimulationRequest.model_validate(body)
    result=gateway.validate_evidence(payload(args),args)
    assert result['available'] is True
    evidence=result['evidence']
    assert evidence['observed_milk_yield_l_day']==18
    assert evidence['baseline_predicted_milk_yield_l_day']==20
    assert evidence['target_period']=='2020-01-11' and evidence['observed_date']=='2020-01-10'
    assert evidence['source_core_version'] is None and evidence['operational_feasibility_validated'] is False
    assert 'cow_state' not in evidence and 'must-not-copy-cow-state' not in str(evidence)
    assert 'Fictional limitation' in result['warnings']


@pytest.mark.parametrize('fields',[
 {},dict(animal_ref='A_SYNTHETIC_1'),dict(animal_ref='A_PLACEHOLDER',thi_mean=68),
 dict(animal_ref='source-id-1',thi_mean=68),dict(animal_ref='A_SYNTHETIC_1',thi_mean=float('nan')),
 dict(animal_ref='A_SYNTHETIC_1',milkings_per_day=0),dict(animal_ref='A_SYNTHETIC_1',milkings_per_day=-1),
 dict(animal_ref='A_SYNTHETIC_1',thi_mean=True),dict(animal_ref='A_SYNTHETIC_1',thi_mean='68'),
 dict(animal_ref='A_SYNTHETIC_1',thi_mean=68,model_path='unapproved'),
 dict(animal_ref='A_SYNTHETIC_1',thi_mean=68,prediction_horizon_days=7),
 dict(animal_ref='A_SYNTHETIC_1',thi_mean=68,change_percent=10),
])
def test_invalid_or_provisional_requests_are_rejected(fields):
    with pytest.raises(ValueError):gateway.ScenarioInput.model_validate(fields)


@pytest.mark.parametrize('change',[
 dict(contract_version='2'),dict(animal_ref='A_OTHER'),dict(prediction_horizon_days=7),
 dict(prediction_horizon_days=True),dict(observed_date='not-a-date'),dict(demo=True),
 dict(baseline_predicted_milk_yield_l_day=float('inf')),dict(model_version='wrong-model'),
])
def test_wrong_provenance_or_nonfinite_evidence_is_rejected(change):
    raw=payload();raw.update(change)
    with pytest.raises(ValueError):gateway.validate_evidence(raw,request())


@pytest.mark.parametrize('change',[
 dict(proposed_value=67),dict(feature='milkings_per_day'),dict(unit='kg/day'),
 dict(absolute_yield_change_l_day=9),dict(absolute_yield_change_l_day=True),dict(percentage_yield_change=99),
 dict(counterfactual_predicted_milk_yield_l_day=float('nan')),
 dict(baseline_predicted_milk_yield_l_day=19),dict(model_version='other'),dict(baseline_value=None),
])
def test_mismatched_scenarios_or_arithmetic_are_rejected(change):
    raw=payload();raw['scenarios'][0].update(change)
    with pytest.raises(ValueError):gateway.validate_evidence(raw,request())


@pytest.mark.parametrize('scenario_status,support',[
 ('OUTSIDE_TRAINING_SUPPORT','OUTSIDE_TRAINING_SUPPORT'),
 ('BASELINE_FEATURE_UNAVAILABLE','NOT_ASSESSED'),
 ('PREDICTION_UNAVAILABLE','NOT_ASSESSED'),
 ('ESTIMATED_MODEL_INPUT_PERTURBATION','RANGE_UNAVAILABLE'),
])
def test_withheld_and_unchecked_estimates_never_become_success(scenario_status,support):
    raw=payload();raw['scenarios'][0].update(scenario_status=scenario_status,model_support_status=support)
    result=gateway.validate_evidence(raw,request())
    assert result['available'] is False
    assert result['evidence']['counterfactual_predicted_milk_yield_l_day'] is None
    assert result['evidence']['percentage_yield_change'] is None


def test_missing_model_preserves_measured_yield_without_filling_predictions():
    raw=payload();raw.update(baseline_status='UNAVAILABLE',baseline_predicted_milk_yield_l_day=None,model_version=None)
    raw['scenarios'][0].update(scenario_status='PREDICTION_UNAVAILABLE',model_support_status='NOT_ASSESSED',
        baseline_predicted_milk_yield_l_day=None,counterfactual_predicted_milk_yield_l_day=None,
        absolute_yield_change_l_day=None,percentage_yield_change=None,model_version=None)
    result=answer_chat(ChatQuery(query='Run a what-if simulation',simulation=request()),simulation_invoke=lambda args:raw)
    assert result['status']=='unavailable' and result['simulation_state']=='not_ready'
    assert result['evidence']['observed_milk_yield_l_day']==18
    assert result['evidence']['baseline_predicted_milk_yield_l_day'] is None


@pytest.mark.parametrize('language,question',[
 ('en','Run a THI what-if'),('si','THI අනුකරණයක් කරන්න'),('ta','THI மாற்றத்தை உருவகப்படுத்துங்கள்'),
])
def test_three_languages_require_explicit_scenario_then_explain_only_validated_facts(language,question):
    invoke=Mock(return_value=payload())
    first=answer_chat(ChatQuery(query=question,language=language),simulation_invoke=invoke)
    assert first['status']=='information' and first['context']['awaiting'] is None
    assert first['simulation_state']=='general' and 'action' not in first
    invoke.assert_not_called()
    result=answer_chat(ChatQuery(query=question,language=language,simulation=request()),simulation_invoke=invoke)
    assert result['status']=='success' and result['tool']=='c2_simulation'
    assert result['evidence']['demo'] is False and result['cloud_processing'] is False
    for value in ('20.00','22.00','+2.00','2020-01-10','2020-01-11','synthetic-model-v1'):
        assert value in result['answer']
    assert result['language']==language


@pytest.mark.parametrize('question',[
 'Run a feed simulation','Simulate concentrate changes','Why would this what-if cause a cure?',
 'Run what-if on 2020-01-01','Herd summary',
])
def test_unsupported_and_hidden_scenario_requests_never_invoke_c2(question):
    invoke=Mock(side_effect=AssertionError('No API call'))
    result=answer_chat(ChatQuery(query=question,simulation=request()),simulation_invoke=invoke)
    assert result['status'] in ('unsupported','invalid_request')
    invoke.assert_not_called()


def test_api_failure_never_exposes_private_details_or_demo_results():
    result=answer_chat(ChatQuery(query='Run a what-if',simulation=request()),
        simulation_invoke=Mock(side_effect=RuntimeError('synthetic-private-diagnostic')))
    assert result['status']=='unavailable' and 'evidence' not in result
    assert 'synthetic-private-diagnostic' not in str(result)


def test_http_client_can_only_use_loopback_and_fixed_endpoint(monkeypatch):
    factory=MagicMock();client=factory.return_value.__enter__.return_value
    response=client.stream.return_value.__enter__.return_value
    response.iter_bytes.return_value=[json.dumps(payload()).encode()]
    monkeypatch.setattr(gateway.httpx,'Client',factory)
    monkeypatch.setenv('C3_C2_API_PORT','8001')
    assert gateway.call_c2(request())['contract_version']=='1.1'
    assert factory.call_args.kwargs['trust_env'] is False and factory.call_args.kwargs['follow_redirects'] is False
    assert client.stream.call_args.args==('POST','http://127.0.0.1:8001/api/v1/interventions/simulate-counterfactual')
    assert client.stream.call_args.kwargs['json']==request().producer_request()
    monkeypatch.setenv('C3_C2_API_PORT','https://external.invalid')
    with pytest.raises(gateway.C2Unavailable):gateway.call_c2(request())
    assert client.stream.call_count==1


def test_large_response_fails_safely_and_releases_the_inference_lock(monkeypatch):
    factory=MagicMock();client=factory.return_value.__enter__.return_value
    response=client.stream.return_value.__enter__.return_value
    response.iter_bytes.return_value=[b'x'*(1024*1024+1)]
    monkeypatch.setattr(gateway.httpx,'Client',factory)
    with pytest.raises(gateway.C2Unavailable):gateway.call_c2(request())
    assert gateway._request_lock.acquire(blocking=False)
    gateway._request_lock.release()


@pytest.mark.parametrize('combined',[False,True])
def test_c3_consumes_the_real_c2_api_contract_using_only_a_fictional_repository_and_predictor(monkeypatch,combined):
    from backend.app.api.routes import interventions
    from components.member1_didt.schemas.counterfactual import CowState
    from components.member1_didt.services.intervention_pipeline import run_simulation
    state=CowState(animal_ref='A_SYNTHETIC_1',observed_date='2020-01-10',milk_yield_l_day=20,
        days_in_milk=30,thi_mean=70,milkings_per_day=2)
    class Predictor:
        model_version='synthetic-contract-test'
        metadata=dict(observed_numeric_support=dict(thi_mean=dict(minimum=50,maximum=90),milkings_per_day=dict(minimum=1,maximum=4)))
        def predict(self,cow,horizon_days=1):return 20+(70-cow.thi_mean)*.1+(cow.milkings_per_day-2)
    repository=Mock();repository.get_current_state.return_value=state
    monkeypatch.setattr(interventions,'run_simulation',lambda body:run_simulation(body,repository=repository,predictor=Predictor()))
    app=FastAPI();app.include_router(interventions.router,prefix='/api/v1');client=TestClient(app)
    def invoke(args):
        response=client.post('/api/v1/interventions/simulate-counterfactual',json=args.producer_request())
        assert response.status_code==200
        return response.json()
    args=request(milkings_per_day=3) if combined else request()
    result=answer_chat(ChatQuery(query='Run a what-if',simulation=args),simulation_invoke=invoke)
    assert result['status']=='success'
    assert result['evidence']['counterfactual_predicted_milk_yield_l_day']==pytest.approx(21.2 if combined else 20.2)
    repository.get_current_state.assert_called_once_with('A_SYNTHETIC_1')


def test_existing_c3_chat_api_accepts_explicit_simulation_and_rejects_model_paths(monkeypatch):
    from backend.app.api.routes import agent
    monkeypatch.setattr(gateway,'call_c2',lambda args:payload(args))
    app=FastAPI();app.include_router(agent.router);client=TestClient(app)
    body=dict(query='Run a what-if simulation',language='ta',simulation=dict(animal_ref='A_SYNTHETIC_1',thi_mean=68))
    response=client.post('/agent/chat',json=body)
    assert response.status_code==200 and response.json()['status']=='success'
    assert response.json()['language']=='ta' and response.json()['cloud_processing'] is False
    body['simulation']['model_path']='unapproved'
    assert client.post('/agent/chat',json=body).status_code==422
