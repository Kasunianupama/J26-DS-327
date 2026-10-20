"""One-feature, model-based what-if estimates; not a causal estimator."""
import math
from hashlib import sha256

from components.member1_didt.prediction.predictor import MilkYieldPredictor, PredictorUnavailable
from components.member1_didt.schemas.counterfactual import (
    CowState, InterventionScenario, ScenarioEstimate,
)
from components.member1_didt.simulation.counterfactual_scenario import FEATURE_TO_FIELD, apply_scenario

# These are model-input what-ifs only. Observed intake is not mapped to a
# controllable ration change, and THI is an exposure, not a cooling action.
SUPPORTED_MODEL_INPUTS = {
    ("heat", "thi_mean", "THI"),
    ("management", "milkings_per_day", "milkings/day"),
}


class CounterfactualSimulator:
    """Use one predictor for the baseline and all independent scenario states."""

    def __init__(self, predictor: MilkYieldPredictor | None):
        self.predictor = predictor

    @staticmethod
    def _scenario_id(scenario: InterventionScenario, index: int) -> str:
        if scenario.scenario_id:
            return scenario.scenario_id
        material = f"{index}|{scenario.category}|{scenario.feature}|{scenario.proposed_value}|{scenario.name}"
        return f"scenario-{index:02d}-{sha256(material.encode()).hexdigest()[:8]}"

    def run(self, state: CowState, scenarios: list[InterventionScenario], horizon_days: int = 1
            ) -> tuple[float | None, str | None, list[ScenarioEstimate], list[str]]:
        warnings: list[str] = []
        baseline: float | None = None
        model_version = None
        if self.predictor is None:
            warnings.append("No compatible Farm X model artifact is installed; yield estimates are unavailable.")
        else:
            try:
                baseline = float(self.predictor.predict(state, horizon_days))
                if not math.isfinite(baseline) or baseline < 0:
                    raise PredictorUnavailable("The model returned an invalid yield estimate.")
                model_version = self.predictor.model_version
            except PredictorUnavailable as exc:
                warnings.append(str(exc))
            except Exception:
                warnings.append("Baseline prediction failed; internal model details are withheld.")

        metadata = getattr(self.predictor, "metadata", {}) if self.predictor is not None else {}
        support = metadata.get("observed_numeric_support", {})
        results: list[ScenarioEstimate] = []
        for index, scenario in enumerate(scenarios, start=1):
            scenario_id = self._scenario_id(scenario, index)
            field = FEATURE_TO_FIELD[scenario.feature]
            baseline_value = getattr(state, field)
            counterfactual = absolute_change = percentage_change = None
            result_status = "ESTIMATED_MODEL_INPUT_PERTURBATION"
            scenario_warnings = [
                "This is a model-input perturbation, not a verified causal intervention effect.",
                "A predicted difference may not occur in the real world.",
            ]

            if (scenario.category, scenario.feature, scenario.unit) not in SUPPORTED_MODEL_INPUTS:
                result_status = "UNSUPPORTED_INTERVENTION_SEMANTICS"
                scenario_warnings.append(
                    "Farm X records this feature, but its units or mapping to a controllable intervention are not established."
                )
            elif baseline_value is None:
                result_status = "BASELINE_FEATURE_UNAVAILABLE"
                scenario_warnings.append("The observed baseline feature value is missing; no counterfactual state was created.")
            elif self.predictor is None or baseline is None:
                result_status = "PREDICTION_UNAVAILABLE"
                scenario_warnings.append("The baseline model prediction is unavailable; no counterfactual estimate was returned.")
            else:
                feature_support = support.get(scenario.feature)
                minimum = feature_support.get("minimum") if feature_support else None
                maximum = feature_support.get("maximum") if feature_support else None
                if minimum is not None and maximum is not None and not minimum <= scenario.proposed_value <= maximum:
                    result_status = "OUTSIDE_TRAINING_SUPPORT"
                    scenario_warnings.append(
                        f"Proposed value is outside observed training range [{minimum}, {maximum}]; prediction was withheld."
                    )
                else:
                    if minimum is None or maximum is None:
                        scenario_warnings.append("Training support range is unavailable; extrapolation could not be assessed.")
                    try:
                        # model_copy in apply_scenario makes an independent state.
                        modified_state = apply_scenario(state, scenario)
                        counterfactual = float(self.predictor.predict(modified_state, horizon_days))
                        if not math.isfinite(counterfactual) or counterfactual < 0:
                            raise PredictorUnavailable("The model returned an invalid yield estimate.")
                        absolute_change = counterfactual - baseline
                        percentage_change = absolute_change / baseline * 100 if baseline else None
                        if baseline == 0:
                            scenario_warnings.append("Percentage change is unavailable because baseline prediction is zero.")
                    except Exception:
                        result_status = "PREDICTION_UNAVAILABLE"
                        scenario_warnings.append("Counterfactual prediction failed; internal model details are withheld.")
                        counterfactual = absolute_change = percentage_change = None

            if scenario.feature == "thi_mean":
                scenario_warnings.append("Changing THI represents an exposure what-if; it does not model a cooling action.")
            if scenario.feature == "milkings_per_day":
                scenario_warnings.append("Labor, equipment, cost, welfare, and operational feasibility are not assessed by this simulator.")
            results.append(ScenarioEstimate(
                scenario_id=scenario_id,
                category=scenario.category,
                name=scenario.name,
                intervention_description=scenario.intervention_description,
                feature=scenario.feature,
                scenario_status=result_status,
                baseline_value=baseline_value,
                proposed_value=scenario.proposed_value,
                unit=scenario.unit,
                change_applied=scenario.proposed_value - baseline_value if baseline_value is not None else None,
                baseline_predicted_milk_yield_l_day=baseline,
                counterfactual_predicted_milk_yield_l_day=counterfactual,
                absolute_yield_change_l_day=absolute_change,
                percentage_yield_change=percentage_change,
                model_version=model_version,
                assumptions=[
                    "Only the named model feature changes; all other observed baseline features are held fixed.",
                    "The model is observational and the estimate does not identify a causal treatment effect.",
                ],
                data_limitations=list(state.data_limitations),
                warnings=scenario_warnings,
            ))
        return baseline, model_version, results, warnings
