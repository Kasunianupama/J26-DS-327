from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.routes import interventions
from components.member1_didt.schemas.counterfactual import CowState, SimulationResponse


app = FastAPI()
app.include_router(interventions.router, prefix="/api/v1")
client = TestClient(app)


def response(animal_ref="SYNTH-API-1"):
    state = CowState(animal_ref=animal_ref, observed_date="2026-01-02", milk_yield_l_day=21.5)
    return SimulationResponse(
        animal_ref=animal_ref, observed_date=state.observed_date, observed_milk_yield_l_day=21.5,
        cow_state=state, prediction_horizon_days=1, baseline_status="UNAVAILABLE",
        scenarios=[], warnings=["No model artifact available."],
    )


def test_simulator_endpoint_contract(monkeypatch):
    import backend.app.api.routes.interventions as route
    monkeypatch.setattr(route, "run_simulation", lambda request: response(request.animal_ref))
    result = client.post("/api/v1/interventions/simulate-counterfactual", json={
        "animal_ref": "SYNTH-API-1",
        "scenarios": [{"scenario_id": "whatif-1", "category": "heat", "name": "THI what-if",
                       "feature": "thi_mean", "proposed_value": 68, "unit": "THI"}],
    })
    assert result.status_code == 200
    assert result.json()["baseline_status"] == "UNAVAILABLE"
    assert result.json()["cow_state"]["milk_yield_l_day"] == 21.5


def test_request_validation_and_legacy_endpoint_regression():
    bad = client.post("/api/v1/interventions/simulate-counterfactual", json={
        "animal_ref": "SYNTH-API-1",
        "scenarios": [{"category": "reproduction", "name": "bad", "feature": "pregnancy",
                       "proposed_value": 1, "unit": "day"}],
    })
    assert bad.status_code == 422
    too_many = client.post("/api/v1/interventions/simulate-counterfactual", json={
        "animal_ref": "SYNTH-API-1",
        "scenarios": [{"scenario_id": str(index), "category": "heat", "name": "what-if",
                       "feature": "thi_mean", "proposed_value": 68, "unit": "THI"} for index in range(9)],
    })
    assert too_many.status_code == 422
    legacy = client.post("/api/v1/interventions/simulate", json={
        "farm_id": "FARM_01", "intervention": "feed", "change_percent": 5,
    })
    assert legacy.status_code == 200
    assert legacy.json()["predicted_yield_change_percent"] is None
    assert legacy.json()["validated"] is False


def test_api_rejects_feed_concentrate_and_mismatched_scenarios():
    unsupported_scenarios = [
        {"category": "feed", "name": "feed", "feature": "dry_matter_intake",
         "proposed_value": 20, "unit": "kg/day"},
        {"category": "supplement", "name": "concentrate", "feature": "concentrate_intake",
         "proposed_value": 7, "unit": "kg/day"},
        {"category": "heat", "name": "wrong feature", "feature": "milkings_per_day",
         "proposed_value": 2, "unit": "milkings/day"},
        {"category": "management", "name": "wrong feature", "feature": "thi_mean",
         "proposed_value": 68, "unit": "THI"},
    ]
    for unsupported in unsupported_scenarios:
        result = client.post("/api/v1/interventions/simulate-counterfactual", json={
            "animal_ref": "SYNTH-API-1", "scenarios": [unsupported],
        })
        assert result.status_code == 422


def test_api_rejects_nonpositive_milking_frequency():
    for value in (0, -1):
        result = client.post("/api/v1/interventions/simulate-counterfactual", json={
            "animal_ref": "SYNTH-API-1", "scenarios": [{
                "category": "management", "name": "frequency", "feature": "milkings_per_day",
                "proposed_value": value, "unit": "milkings/day",
            }],
        })
        assert result.status_code == 422


def test_api_accepts_combined_only_alternative(monkeypatch):
    import backend.app.api.routes.interventions as route
    received = []
    monkeypatch.setattr(route, "run_simulation", lambda request: (received.append(request) or response()))
    result = client.post("/api/v1/interventions/simulate-counterfactual", json={
        "animal_ref": "SYNTH-API-1",
        "scenarios": [],
        "combined_scenario": {"scenario_id": "both", "thi_mean": 68, "milkings_per_day": 3},
    })
    assert result.status_code == 200
    assert received[0].combined_scenario.thi_mean == 68
    assert received[0].scenarios == []


def test_missing_animal_and_database_failure_return_safe_http_errors(monkeypatch):
    import backend.app.api.routes.interventions as route
    from components.member1_didt.services.farmx_repository import AnimalNotFound, FarmXDataUnavailable

    def missing(ref): raise AnimalNotFound("private animal details")
    monkeypatch.setattr(route.FarmXRepository, "get_current_state", lambda self, ref: missing(ref))
    not_found = client.get("/api/v1/interventions/cows/SYNTH-API-1/state")
    assert not_found.status_code == 404
    assert "private" not in not_found.text

    def unavailable(request): raise FarmXDataUnavailable("role is not configured")
    monkeypatch.setattr(route, "run_simulation", unavailable)
    result = client.post("/api/v1/interventions/simulate-counterfactual", json={
        "animal_ref": "SYNTH-API-1", "scenarios": [{"category": "heat", "name": "test",
        "feature": "thi_mean", "proposed_value": 68, "unit": "THI"}],
    })
    assert result.status_code == 503
    assert "role is not configured" in result.text


def test_available_animal_selector_returns_only_approved_reference_and_date(monkeypatch):
    import backend.app.api.routes.interventions as route
    from components.member1_didt.schemas.counterfactual import CowReference
    monkeypatch.setattr(route.FarmXRepository, "list_available_animals",
                        lambda self, limit: [CowReference(animal_ref="SYNTH-API-1", observed_date="2026-01-02")])
    result = client.get("/api/v1/interventions/cows")
    assert result.status_code == 200
    assert result.json() == [{"animal_ref": "SYNTH-API-1", "observed_date": "2026-01-02"}]
