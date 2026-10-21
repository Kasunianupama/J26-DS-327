"""Application service that composes only data loading, prediction and simulation."""
from components.member1_didt.prediction.predictor import FarmXMilkYieldPredictor, PredictorUnavailable
from components.member1_didt.schemas.counterfactual import (
    CombinedScenarioInput, CowState, InterventionScenario, SimulationRequest, SimulationResponse,
)
from components.member1_didt.services.farmx_repository import FarmXRepository
from components.member1_didt.simulation.biological_intervention_simulator import CounterfactualSimulator
from components.member1_didt.recommendation.intervention_recommender import rank_and_recommend


def run_simulation(request: SimulationRequest, repository: FarmXRepository | None = None,
                   predictor=None) -> SimulationResponse:
    """Load the latest approved state and estimate requested model-input what-ifs."""
    state: CowState = (repository or FarmXRepository()).get_current_state(request.animal_ref)
    warnings = list(state.data_limitations)
    if predictor is None:
        try:
            predictor = FarmXMilkYieldPredictor()
        except PredictorUnavailable as exc:
            warnings.append(str(exc))
    simulation = CounterfactualSimulator(predictor).run(
        state, request.scenarios, request.prediction_horizon_days, request.combined_scenario,
    )
    warnings.extend(simulation.warnings)
    ranked, recommendation, recommendation_explanation = rank_and_recommend(
        simulation.scenarios, simulation.combined_scenario,
    )
    return SimulationResponse(
        animal_ref=state.animal_ref,
        observed_date=state.observed_date,
        observed_milk_yield_l_day=state.milk_yield_l_day,
        prediction_horizon_days=request.prediction_horizon_days,
        baseline_status="AVAILABLE" if simulation.baseline is not None else "UNAVAILABLE",
        baseline_predicted_milk_yield_l_day=simulation.baseline,
        model_version=simulation.model_version,
        cow_state=state,
        scenarios=simulation.scenarios,
        combined_scenario=simulation.combined_scenario,
        ranked_alternatives=ranked,
        recommendation=recommendation,
        recommendation_explanation=recommendation_explanation,
        warnings=warnings,
    )


def make_simulation_request(animal_ref: str, scenarios: list[InterventionScenario],
                            horizon_days: int = 1,
                            combined_scenario: CombinedScenarioInput | None = None) -> SimulationRequest:
    return SimulationRequest(
        animal_ref=animal_ref, scenarios=scenarios, prediction_horizon_days=horizon_days,
        combined_scenario=combined_scenario,
    )
