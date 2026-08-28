from shared.schemas.intervention import InterventionRecommendation, InterventionScenario

def simulate(scenario: InterventionScenario) -> dict:
    uplift = round(max(-5, min(8, scenario.change_percent * 0.12)), 1)
    return {"scenario": scenario, "predicted_yield_change_percent": uplift, "validated": True, "recommendations": [InterventionRecommendation(action="Review the feeding plan with the farm nutrition lead.", rationale="Deterministic scaffold demonstration.", priority="medium")]}

