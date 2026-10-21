from datetime import date, timedelta

import pandas as pd
import pytest
import joblib
from pydantic import ValidationError

from components.member1_didt.prediction.model_training import train_and_evaluate
from components.member1_didt.prediction.predictor import (
    FEATURES, FarmXMilkYieldPredictor, PredictorUnavailable,
)
from components.member1_didt.schemas.counterfactual import (
    CombinedScenarioInput, CowState, InterventionScenario, SimulationRequest,
)
from components.member1_didt.simulation.biological_intervention_simulator import CounterfactualSimulator
from components.member1_didt.simulation.counterfactual_scenario import apply_scenario
from components.member1_didt.recommendation.intervention_recommender import rank_and_recommend
from components.member1_didt.services.intervention_pipeline import run_simulation


def cow(**updates):
    values = {"animal_ref": "SYNTH-UNIT-1", "observed_date": "2026-01-10", "breed": "Test Breed",
              "milk_yield_l_day": 22.0, "days_in_milk": 100, "lactation_no": 2,
              "milkings_per_day": 2.0, "thi_mean": 70.0, "dry_matter_intake": 18.0,
              "concentrate_intake": 6.0, "data_limitations": []}
    values.update(updates)
    return CowState(**values)


def scenario(feature="thi_mean", value=68.0, category="heat", unit="THI", scenario_id="s-1"):
    return InterventionScenario(scenario_id=scenario_id, category=category, name="What-if",
                                feature=feature, proposed_value=value, unit=unit)


class FakePredictor:
    model_version = "synthetic-test-only"
    metadata = {"observed_numeric_support": {
        "thi_mean": {"minimum": 50, "maximum": 85},
        "milkings_per_day": {"minimum": 1, "maximum": 4},
    }}

    def __init__(self, fn=None): self.states, self.fn = [], fn
    def predict(self, state, horizon_days=1):
        self.states.append(state)
        if self.fn: return self.fn(state)
        return 30 - state.thi_mean / 10


def test_baseline_and_counterfactual_use_same_model_and_calculate_changes():
    baseline_state = cow()
    predictor = FakePredictor()
    run = CounterfactualSimulator(predictor).run(
        baseline_state, [scenario()], 1,
    )
    result = run.scenarios[0]
    assert run.baseline == pytest.approx(23)
    assert run.model_version == "synthetic-test-only"
    assert result.counterfactual_predicted_milk_yield_l_day == pytest.approx(23.2)
    assert result.absolute_yield_change_l_day == pytest.approx(.2)
    assert result.percentage_yield_change == pytest.approx(.2 / 23 * 100)
    assert result.scenario_status == "ESTIMATED_MODEL_INPUT_PERTURBATION"
    assert len(predictor.states) == 2
    assert predictor.states[0].thi_mean == 70 and predictor.states[1].thi_mean == 68
    assert baseline_state.thi_mean == 70
    assert not run.warnings


def test_multiple_scenarios_are_independent_and_original_state_is_unchanged():
    state = cow()
    predictor = FakePredictor()
    run = CounterfactualSimulator(predictor).run(
        state, [scenario(value=68, scenario_id="first"), scenario(value=72, scenario_id="second")],
    )
    results = run.scenarios
    assert [item.scenario_id for item in results] == ["first", "second"]
    assert predictor.states[0].thi_mean == 70
    assert predictor.states[1].thi_mean == 68
    assert predictor.states[2].thi_mean == 72
    assert state.thi_mean == 70


def test_milking_frequency_scenario_changes_only_milkings_and_is_hypothetical():
    state = cow()
    predictor = FakePredictor(fn=lambda current: 20 + current.milkings_per_day)
    intervention = scenario(feature="milkings_per_day", value=3.0, category="management",
                            unit="milkings/day")
    run = CounterfactualSimulator(predictor).run(state, [intervention])

    result = run.scenarios[0]
    assert run.baseline == 22.0
    assert result.counterfactual_predicted_milk_yield_l_day == 23.0
    assert result.absolute_yield_change_l_day == 1.0
    assert predictor.states[1].milkings_per_day == 3.0
    assert predictor.states[1].thi_mean == state.thi_mean
    assert predictor.states[1].milk_yield_l_day == state.milk_yield_l_day
    assert state.milkings_per_day == 2.0
    assert any("operational feasibility are not assessed" in w for w in result.warnings)


@pytest.mark.parametrize("scenario_values", [
    {"category": "feed", "feature": "dry_matter_intake", "unit": "kg/day"},
    {"category": "supplement", "feature": "concentrate_intake", "unit": "kg/day"},
    {"category": "heat", "feature": "milkings_per_day", "unit": "milkings/day"},
    {"category": "management", "feature": "thi_mean", "unit": "THI"},
    {"category": "heat", "feature": "thi_mean", "unit": "index"},
])
def test_request_rejects_unsupported_intervention_combinations(scenario_values):
    values = {"category": "heat", "feature": "thi_mean", "unit": "THI"}
    values.update(scenario_values)
    with pytest.raises(ValidationError):
        scenario(**values)


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan")])
def test_request_rejects_invalid_milking_frequency_values(value):
    with pytest.raises(ValidationError):
        scenario(feature="milkings_per_day", value=value, category="management", unit="milkings/day")


def test_outside_training_support_is_reported_and_prediction_withheld():
    predictor = FakePredictor()
    run = CounterfactualSimulator(predictor).run(cow(), [scenario(value=90)])
    assert run.scenarios[0].scenario_status == "OUTSIDE_TRAINING_SUPPORT"
    assert run.scenarios[0].counterfactual_predicted_milk_yield_l_day is None
    assert len(predictor.states) == 1


def test_missing_baseline_feature_missing_model_and_zero_baseline_are_explicit():
    predictor = FakePredictor()
    missing_run = CounterfactualSimulator(predictor).run(cow(thi_mean=None), [scenario()])
    assert missing_run.scenarios[0].scenario_status == "BASELINE_FEATURE_UNAVAILABLE"
    assert missing_run.scenarios[0].counterfactual_predicted_milk_yield_l_day is None

    unavailable_run = CounterfactualSimulator(None).run(cow(), [scenario()])
    assert unavailable_run.baseline is None and unavailable_run.warnings
    assert unavailable_run.scenarios[0].scenario_status == "PREDICTION_UNAVAILABLE"
    assert unavailable_run.scenarios[0].counterfactual_predicted_milk_yield_l_day is None
    assert rank_and_recommend(unavailable_run.scenarios, None)[1] is None

    zero_predictor = FakePredictor(fn=lambda state: 0.0)
    zero_run = CounterfactualSimulator(zero_predictor).run(cow(), [scenario()])
    assert zero_run.scenarios[0].absolute_yield_change_l_day == 0
    assert zero_run.scenarios[0].percentage_yield_change is None
    assert any("zero" in warning for warning in zero_run.scenarios[0].warnings)


def test_failed_prediction_does_not_create_fallback_estimate():
    predictor = FakePredictor(fn=lambda state: (_ for _ in ()).throw(RuntimeError("private detail")))
    run = CounterfactualSimulator(predictor).run(cow(), [scenario()])
    assert run.baseline is None
    assert run.scenarios[0].counterfactual_predicted_milk_yield_l_day is None
    assert run.scenarios[0].scenario_status == "PREDICTION_UNAVAILABLE"
    assert "private detail" not in " ".join(run.warnings + run.scenarios[0].warnings)


def test_request_validation_bounds_scenarios_and_values():
    with pytest.raises(Exception):
        SimulationRequest(animal_ref="x", scenarios=[scenario(value=float("nan"))])
    with pytest.raises(Exception):
        SimulationRequest(animal_ref="x", scenarios=[scenario(scenario_id=str(i)) for i in range(9)])
    with pytest.raises(Exception):
        SimulationRequest(animal_ref="x", scenarios=[scenario(scenario_id="same"), scenario(scenario_id="same")])


def test_combined_request_is_bounded_and_can_be_submitted_without_individual_scenarios():
    combined = CombinedScenarioInput(thi_mean=68, milkings_per_day=3)
    request = SimulationRequest(animal_ref="synthetic", scenarios=[], combined_scenario=combined)
    assert request.combined_scenario == combined
    with pytest.raises(ValidationError):
        SimulationRequest(animal_ref="synthetic")
    request_with_full_individual_set = SimulationRequest(
        animal_ref="synthetic", scenarios=[scenario(scenario_id=str(i)) for i in range(8)],
        combined_scenario=combined,
    )
    assert len(request_with_full_individual_set.scenarios) == 8
    assert request_with_full_individual_set.combined_scenario == combined


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan")])
def test_combined_request_rejects_invalid_milking_frequency(value):
    with pytest.raises(ValidationError):
        CombinedScenarioInput(thi_mean=68, milkings_per_day=value)


def test_combined_state_changes_both_supported_features_once_and_preserves_baseline():
    state = cow()
    predictor = FakePredictor(fn=lambda current: 20 + (70 - current.thi_mean) + current.milkings_per_day
                              + (70 - current.thi_mean) * (current.milkings_per_day - 2))
    combined = CombinedScenarioInput(thi_mean=68, milkings_per_day=3, scenario_id="both")
    run = CounterfactualSimulator(predictor).run(state, [], combined_scenario=combined)

    estimate = run.combined_scenario
    assert estimate is not None
    assert run.baseline == 22
    assert estimate.counterfactual_predicted_milk_yield_l_day == 27
    assert estimate.absolute_yield_change_l_day == 5
    assert estimate.percentage_yield_change == pytest.approx(5 / 22 * 100)
    assert len(predictor.states) == 2  # one baseline call, one combined-state call
    assert predictor.states[0].thi_mean == 70 and predictor.states[0].milkings_per_day == 2
    assert predictor.states[1].thi_mean == 68 and predictor.states[1].milkings_per_day == 3
    assert predictor.states[1].milk_yield_l_day == state.milk_yield_l_day
    assert predictor.states[1].days_in_milk == state.days_in_milk
    assert state.thi_mean == 70 and state.milkings_per_day == 2


def test_combined_training_support_checks_both_changed_features_and_withholds_out_of_range():
    for combined in (
        CombinedScenarioInput(thi_mean=90, milkings_per_day=3),
        CombinedScenarioInput(thi_mean=68, milkings_per_day=5),
    ):
        predictor = FakePredictor()
        run = CounterfactualSimulator(predictor).run(cow(), [], combined_scenario=combined)
        assert run.combined_scenario.scenario_status == "OUTSIDE_TRAINING_SUPPORT"
        assert run.combined_scenario.model_support_status == "OUTSIDE_TRAINING_SUPPORT"
        assert run.combined_scenario.counterfactual_predicted_milk_yield_l_day is None
        assert len(predictor.states) == 1  # baseline only; no unsupported prediction
        assert rank_and_recommend([], run.combined_scenario)[1] is None


def test_ranks_individual_and_combined_predictions_and_recommends_highest_yield():
    state = cow()
    predictor = FakePredictor(fn=lambda current: 20 + (70 - current.thi_mean) + current.milkings_per_day
                              + (70 - current.thi_mean) * (current.milkings_per_day - 2))
    run = CounterfactualSimulator(predictor).run(
        state,
        [scenario(value=68, scenario_id="thi"),
         scenario(feature="milkings_per_day", value=3, category="management", unit="milkings/day", scenario_id="milkings")],
        combined_scenario=CombinedScenarioInput(thi_mean=68, milkings_per_day=3, scenario_id="combined"),
    )
    ranked, recommendation, explanation = rank_and_recommend(run.scenarios, run.combined_scenario)

    assert [item.scenario_id for item in ranked] == ["combined", "thi", "milkings"]
    assert recommendation.scenario_id == "combined"
    assert recommendation.rank == 1
    assert recommendation.operational_feasibility_validated is False
    assert "not a causal optimum" in recommendation.explanation
    assert explanation == recommendation.explanation


def test_no_recommendation_when_all_alternatives_are_invalid_or_unavailable():
    predictor = FakePredictor()
    run = CounterfactualSimulator(predictor).run(
        cow(), [scenario(value=90)],
        combined_scenario=CombinedScenarioInput(thi_mean=90, milkings_per_day=3),
    )
    ranked, recommendation, explanation = rank_and_recommend(run.scenarios, run.combined_scenario)
    assert ranked == [] and recommendation is None
    assert "training-support checks" in explanation

    no_model_run = CounterfactualSimulator(None).run(
        cow(), [], combined_scenario=CombinedScenarioInput(thi_mean=68, milkings_per_day=3),
    )
    _, no_model_recommendation, no_model_explanation = rank_and_recommend([], no_model_run.combined_scenario)
    assert no_model_recommendation is None
    assert no_model_run.combined_scenario.counterfactual_predicted_milk_yield_l_day is None
    assert "valid available counterfactual prediction" in no_model_explanation

    unsupported_predictor = FakePredictor()
    unsupported_predictor.metadata = {"observed_numeric_support": {}}
    unknown_support_run = CounterfactualSimulator(unsupported_predictor).run(cow(), [scenario()])
    assert unknown_support_run.scenarios[0].counterfactual_predicted_milk_yield_l_day is not None
    assert unknown_support_run.scenarios[0].model_support_status == "RANGE_UNAVAILABLE"
    _, unknown_support_recommendation, unknown_support_explanation = rank_and_recommend(
        unknown_support_run.scenarios, None,
    )
    assert unknown_support_recommendation is None
    assert "training-support checks" in unknown_support_explanation


def test_pipeline_returns_ranked_recommendation_without_database_access():
    class StubRepository:
        def get_current_state(self, animal_ref):
            return cow(animal_ref=animal_ref)

    request = SimulationRequest(
        animal_ref="SYNTH-PIPELINE-1",
        scenarios=[scenario(value=68)],
        combined_scenario=CombinedScenarioInput(thi_mean=68, milkings_per_day=3),
    )
    predictor = FakePredictor(fn=lambda current: 20 + (70 - current.thi_mean) + current.milkings_per_day
                              + (70 - current.thi_mean) * (current.milkings_per_day - 2))
    response = run_simulation(request, repository=StubRepository(), predictor=predictor)
    assert response.ranked_alternatives[0].alternative_type == "combined"
    assert response.recommendation.scenario_id == "combined-thi-milkings"
    assert response.baseline_predicted_milk_yield_l_day == 22


def test_model_artifact_missing_fails_explicitly(tmp_path):
    with pytest.raises(PredictorUnavailable):
        FarmXMilkYieldPredictor(tmp_path / "missing.joblib")


def test_incompatible_model_artifact_reports_safe_version_failure(tmp_path):
    target = tmp_path / "incompatible.joblib"
    joblib.dump({
        "estimator": object(),
        "metadata": {"scikit_learn_version": "0.0-incompatible", "model_version": "synthetic"},
    }, target)

    with pytest.raises(PredictorUnavailable, match="different scikit-learn version"):
        FarmXMilkYieldPredictor(target)


def test_current_state_body_weight_is_passed_to_the_model_feature_frame():
    class CapturingEstimator:
        def predict(self, frame):
            self.frame = frame.copy()
            return [24.0]

    predictor = FarmXMilkYieldPredictor.__new__(FarmXMilkYieldPredictor)
    predictor.estimator = CapturingEstimator()
    predictor.model_version = "synthetic-test-only"

    assert predictor.predict(cow(body_weight=537.5)) == 24.0
    assert predictor.estimator.frame.loc[0, "body_weight"] == 537.5


def test_training_uses_chronological_holdout_and_records_empirical_support(tmp_path):
    rows = []
    start = date(2025, 1, 1)
    for i in range(420):
        row = {feature: ("Test Breed" if feature == "breed" else float(i % 20 + 1)) for feature in FEATURES}
        row.update(milk_date=start + timedelta(days=i), target_yield_l_day=20 + i % 17)
        rows.append(row)
    target = tmp_path / "model.joblib"
    report = train_and_evaluate(pd.DataFrame(rows), target, max_train_rows=500, max_test_rows=500)
    assert report.train_end_date < report.test_start_date
    assert report.test_rows == 180
    assert target.is_file()
    predictor = FarmXMilkYieldPredictor(target)
    assert predictor.model_version == report.model_version
    prediction = predictor.predict(cow())
    assert pd.notna(prediction)
