"""Create a single-variable counterfactual state without mutating its baseline."""
from components.member1_didt.schemas.counterfactual import CowState, InterventionScenario

FEATURE_TO_FIELD = {
    "thi_mean": "thi_mean",
    "milkings_per_day": "milkings_per_day",
}


def apply_scenario(state: CowState, scenario: InterventionScenario) -> CowState:
    field = FEATURE_TO_FIELD.get(scenario.feature)
    if field is None:
        raise ValueError("Unsupported counterfactual feature.")
    return state.model_copy(update={field: scenario.proposed_value})
