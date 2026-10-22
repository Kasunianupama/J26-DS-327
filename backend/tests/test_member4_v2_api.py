"""Standalone synthetic FastAPI application; no settings or live engine."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.api.routes import member4_research as routes
from components.member4_crisis_forecasting.services.published_api import PublishedOutputService
from components.member4_crisis_forecasting.output.publisher import prepare_publication
from components.member4_crisis_forecasting.tests.test_v2_outputs import generate
from backend.tests.test_member4_research_api import FakeEngine


def test_v2_query_uses_only_v2_and_returns_valid_payload(monkeypatch):
    outputs, _ = generate()
    engine = FakeEngine([prepare_publication(outputs[0])])
    monkeypatch.setattr(routes, 'published_output_service', PublishedOutputService(lambda: engine, enabled=True))
    app = FastAPI(); app.include_router(routes.router, prefix='/api/v1/risks')
    app.dependency_overrides[routes.require_member4_read] = lambda: None
    api = TestClient(app)
    result = api.get('/api/v1/risks/research/farms/FARM_X/assessments?scoring_version=v2')
    assert result.status_code == 200
    assert result.json()['items'][0]['scoring_config']['version'] == 'fictional-scoring-v2'
    assert 'farm_risk_assessment_v2' in engine.calls[1][0]
    assert api.get('/api/v1/risks/research/farms/FARM_X/assessments?scoring_version=unsafe').status_code == 422


def test_v2_remains_authorized_and_mixed_version_rejected(monkeypatch):
    outputs, _ = generate()
    first, second = prepare_publication(outputs[0]), prepare_publication(outputs[1])
    second['payload']['scoring_config']['version'] = 'other'; second['scoring_version'] = 'other'
    engine = FakeEngine([first, second])
    monkeypatch.setattr(routes, 'published_output_service', PublishedOutputService(lambda: engine, enabled=True))
    monkeypatch.delenv('C4_LOCAL_READ_ONLY', raising=False)
    monkeypatch.setenv('C4_LOCAL_AUTH_ENABLED', 'off')
    app = FastAPI(); app.include_router(routes.router, prefix='/api/v1/risks')
    api = TestClient(app)
    path = '/api/v1/risks/research/farms/FARM_X/assessments?scoring_version=v2'
    assert api.get(path).status_code == 403
    app.dependency_overrides[routes.require_member4_read] = lambda: None
    assert api.get(path).status_code == 503
