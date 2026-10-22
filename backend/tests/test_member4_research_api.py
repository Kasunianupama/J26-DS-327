"""Synthetic outputs and fake engine only; no app/settings/.env import or DB."""
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.authentication import AuthCredentials, SimpleUser, UnauthenticatedUser

from backend.app.api.routes import member4_research as routes
from components.member4_crisis_forecasting.services.published_api import (
    PublishedOutputService, validate_record, PublishedUnavailable,
)
from components.member4_crisis_forecasting.tests.test_scoring_output import make_output
from components.member4_crisis_forecasting.output.publisher import prepare_publication


def assessment():
    payload = make_output().model_dump(mode="json")
    payload.update(assessment_date="2025-01-01", assessment_cutoff="2025-01-01T23:59:59Z",
                   generated_at="2025-01-01T23:59:59Z")
    # Fictional fixture exercising the published contract, never actual farm data.
    payload["provenance"]["source"] = "published"
    from components.member4_crisis_forecasting.schemas.risk_output import validate_research_output
    return prepare_publication(validate_research_output(payload))


def prediction():
    payload = dict(contract_version="1.0.0", prediction_id=str(UUID(int=2)), farm_id="FARM_X",
        assessment_date="2022-02-01", generated_at="2025-01-01T00:00:00Z",
        artifact_version="1.0.0", artifact_sha256="a" * 64,
        model_status="random_forest_experimental_not_live_validated", research_only=True,
        live_warning_allowed=False, predicted_decline_probability=.2,
        probability_interpretation="uncalibrated_experimental_model_score", saved_threshold=None,
        predicted_decline=None, classification_status="no_saved_threshold", actual_outcome=None,
        outcome_reason="incomplete_calendar_window", experiment_partition="test_exploratory",
        milk_source="shipment", historical_availability="unknown", recording_completeness="unknown",
        configuration=dict(milk_source="shipment", decline_threshold_pct=10, decision_threshold=.5,
                           train_end="2021-01-01", validation_end="2022-01-01", test_end="2022-04-01"))
    from components.member4_crisis_forecasting.prediction.research_prediction import ResearchPrediction
    payload = ResearchPrediction.model_validate(payload).model_dump(mode="json")
    return {**{k: v for k, v in payload.items() if k != "configuration"}, "payload": payload}


class FakeEngine:
    def __init__(self, rows): self.rows, self.calls = rows, []
    def connect(self): return self
    def begin(self): return self
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def dispose(self): pass
    def execute(self, sql, params=None):
        self.calls.append((str(sql), params))
        return self
    def mappings(self): return self.rows


def client(monkeypatch, rows, authorized=True, scopes=("member4:read",)):
    engine = FakeEngine(rows)
    monkeypatch.setattr(routes, "published_output_service", PublishedOutputService(lambda: engine, enabled=True))
    app = FastAPI()
    @app.middleware("http")
    async def synthetic_auth(request, call_next):
        request.scope["user"] = SimpleUser("fictional") if authorized else UnauthenticatedUser()
        request.scope["auth"] = AuthCredentials(list(scopes))
        return await call_next(request)
    app.include_router(routes.router, prefix="/api/v1/risks")
    return TestClient(app), engine


@pytest.mark.parametrize("endpoint,fixture", [("assessments", assessment), ("milk-decline-predictions", prediction)])
def test_complete_output(monkeypatch, endpoint, fixture):
    row = fixture()
    api, engine = client(monkeypatch, [row])
    response = api.get(f"/api/v1/risks/research/farms/FARM_X/{endpoint}")
    assert response.status_code == 200
    assert response.json()["source"] == "published"
    assert len(response.json()["items"]) == 1
    assert response.json()["items"][0]["research_only"] is True
    assert response.headers["cache-control"] == "no-store"
    assert "READ ONLY" in engine.calls[0][0]
    assert engine.calls[1][1] == {"farm_id": "FARM_X"}


@pytest.mark.parametrize("endpoint", ["assessments", "milk-decline-predictions"])
def test_empty_and_unauthorized(monkeypatch, endpoint):
    api, engine = client(monkeypatch, [], authorized=False)
    assert api.get(f"/api/v1/risks/research/farms/FARM_X/{endpoint}").status_code == 403
    assert engine.calls == []
    api, engine = client(monkeypatch, [], scopes=())
    assert api.get(f"/api/v1/risks/research/farms/FARM_X/{endpoint}").status_code == 403
    assert engine.calls == []
    api, engine = client(monkeypatch, [])
    assert api.get(f"/api/v1/risks/research/farms/FARM_X/{endpoint}").json() == {
        "source": "published", "contract_version": "1.0.0", "items": []}
    assert api.get(f"/api/v1/risks/research/farms/OTHER/{endpoint}").status_code == 404


@pytest.mark.parametrize("endpoint,fixture", [("assessments", assessment), ("milk-decline-predictions", prediction)])
@pytest.mark.parametrize("flag,value", [("research_only", False), ("live_warning_allowed", True), ("research_only", "true")])
def test_invalid_flags_rejected(monkeypatch, endpoint, fixture, flag, value):
    row = fixture(); row["payload"][flag] = value
    api, _ = client(monkeypatch, [row])
    response = api.get(f"/api/v1/risks/research/farms/FARM_X/{endpoint}")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "member4_stored_contract_mismatch"


def test_column_mismatch_and_invalid_payload(monkeypatch):
    row = assessment(); row["combined_score"] = 99
    with pytest.raises(ValueError): validate_record("assessments", row)
    row = prediction(); row["payload"]["predicted_decline_probability"] = 2
    api, _ = client(monkeypatch, [row])
    assert api.get('/api/v1/risks/research/farms/FARM_X/milk-decline-predictions').status_code == 503


def test_disabled_service_never_opens_connection():
    def forbidden(): raise AssertionError("must not connect")
    with pytest.raises(PublishedUnavailable):
        PublishedOutputService(forbidden, enabled=False).read("assessments", "FARM_X")


def test_database_failure_is_sanitized(monkeypatch):
    api, _ = client(monkeypatch, [])
    def failing(): raise RuntimeError("fictional-sensitive-connection-detail")
    monkeypatch.setattr(routes, "published_output_service", PublishedOutputService(failing, enabled=True))
    response = api.get('/api/v1/risks/research/farms/FARM_X/assessments')
    assert response.status_code == 503
    assert "fictional-sensitive" not in response.text


def test_chronological_sorting(monkeypatch):
    first = prediction()
    second = prediction()
    second["prediction_id"] = str(UUID(int=3))
    second["assessment_date"] = "2022-02-02"
    second["payload"]["prediction_id"] = second["prediction_id"]
    second["payload"]["assessment_date"] = second["assessment_date"]
    api, _ = client(monkeypatch, [second, first])
    response = api.get('/api/v1/risks/research/farms/FARM_X/milk-decline-predictions')
    assert response.status_code == 200
    assert [r["assessment_date"] for r in response.json()["items"]] == ["2022-02-01", "2022-02-02"]
