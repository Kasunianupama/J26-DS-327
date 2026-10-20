"""Application service that composes only data loading, prediction and simulation."""
from components.member1_didt.prediction.predictor import FarmXMilkYieldPredictor, PredictorUnavailable
from components.member1_didt.schemas.counterfactual import (
    CowState, InterventionScenario, SimulationRequest, SimulationResponse,
)
from components.member1_didt.services.farmx_repository import FarmXRepository
from components.member1_didt.simulation.biological_intervention_simulator import CounterfactualSimulator


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
    baseline, model_version, estimates, simulation_warnings = CounterfactualSimulator(predictor).run(
        state, request.scenarios, request.prediction_horizon_days,
    )
    warnings.extend(simulation_warnings)
    return SimulationResponse(
        animal_ref=state.animal_ref,
        observed_date=state.observed_date,
        observed_milk_yield_l_day=state.milk_yield_l_day,
        prediction_horizon_days=request.prediction_horizon_days,
        baseline_status="AVAILABLE" if baseline is not None else "UNAVAILABLE",
        baseline_predicted_milk_yield_l_day=baseline,
        model_version=model_version,
        cow_state=state,
        scenarios=estimates,
        warnings=warnings,
    )


def make_simulation_request(animal_ref: str, scenarios: list[InterventionScenario],
                            horizon_days: int = 1) -> SimulationRequest:
    return SimulationRequest(
        animal_ref=animal_ref, scenarios=scenarios, prediction_horizon_days=horizon_days,
    )
