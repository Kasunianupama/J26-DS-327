"""Legacy API response contract with all unsupported demo estimates removed."""
from shared.schemas.intervention import InterventionScenario


def simulate(scenario: InterventionScenario) -> dict:
    return {
        "scenario": scenario,
        "predicted_yield_change_percent": None,
        "validated": False,
        "status": "model_and_data_unavailable_for_legacy_contract",
        "estimate_type": "unavailable",
        "warnings": ["Use /api/v1/interventions/simulate-counterfactual with an actual animal reference; no demo uplift is returned."],
        "recommendations": [],
    }
