"""Standalone synthetic routes and fake engines only; no app settings import."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.api.routes import member4_research as routes
from backend.tests.test_member4_research_api import FakeEngine
from components.member4_crisis_forecasting.services.published_api import PublishedOutputService
from components.member4_crisis_forecasting.tests.test_v3_publication import outputs
from components.member4_crisis_forecasting.output.v3_publication import prepare_v3


def test_v3_api_validates_two_domain_stored_payload_and_requires_auth(monkeypatch):
    engine = FakeEngine([prepare_v3(outputs()[0])])
    monkeypatch.setattr(routes, 'published_output_service', PublishedOutputService(lambda: engine, enabled=True))
    monkeypatch.delenv('C4_LOCAL_READ_ONLY', raising=False); monkeypatch.setenv('C4_LOCAL_AUTH_ENABLED','off')
    app = FastAPI(); app.include_router(routes.router, prefix='/api/v1/risks')
    api = TestClient(app); path = '/api/v1/risks/research/farms/FARM_X/assessments?scoring_version=v3'
    assert api.get(path).status_code == 403 and not engine.calls
    app.dependency_overrides[routes.require_member4_read] = lambda: None
    response = api.get(path)
    assert response.status_code == 200
    payload = response.json()['items'][0]
    assert payload['contract_version'] == '3.0.0' and len(payload['domains']) == 2
    assert payload['combined_score'] == 55 and 'biological' not in payload['contributions']
    assert 'farm_risk_assessment_v3' in engine.calls[1][0]


def test_v3_invalid_payload_and_empty_response(monkeypatch):
    row = prepare_v3(outputs()[0]); row['payload']['combined_score'] = 48.4
    engine = FakeEngine([row])
    monkeypatch.setattr(routes,'published_output_service',PublishedOutputService(lambda:engine,enabled=True))
    app = FastAPI(); app.include_router(routes.router,prefix='/api/v1/risks')
    app.dependency_overrides[routes.require_member4_read] = lambda: None
    api = TestClient(app); path='/api/v1/risks/research/farms/FARM_X/assessments?scoring_version=v3'
    assert api.get(path).status_code == 503
    engine.rows = []
    assert api.get(path).json()['items'] == []
