from components.member3_farmer_reasoning.services.demo_service import answer_query
from shared.schemas.predictive import PredictiveFarmContext
from shared.schemas.user import UserRole


def test_agent_uses_predictive_context_and_requires_verification_for_limited_forecast():
    context = PredictiveFarmContext.model_validate({
        "farm_id": "FARM_01",
        "forecast_window_days": 30,
        "milk_litres_per_day": {"expected": 2840, "lower": 2580, "upper": 3050},
        "drivers": {"milkers": 145, "calvings": 8, "dry_offs": 15, "transition_share": 0.31, "thi": 78},
        "confidence": "Limited",
        "priority_animals": [{"animal_id": "C-104", "reason": "Pregnancy check overdue", "evidence": "Individual + peer"}],
    })

    response = answer_query("What needs review?", "FARM_01", UserRole.FARM_MANAGER, "en", context)

    assert response["predictive_context_used"] is True
    assert response["confidence"] == 0.55
    assert response["evidence"]
    assert any("Verify pregnancy" in item["action"] for item in response["recommendations"])
    assert any("C-104" in item["action"] for item in response["recommendations"])
