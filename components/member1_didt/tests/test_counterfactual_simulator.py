from datetime import date, timedelta

import pandas as pd
import pytest
import joblib

from components.member1_didt.prediction.model_training import train_and_evaluate
from components.member1_didt.prediction.predictor import (
    FEATURES, FarmXMilkYieldPredictor, PredictorUnavailable,
)
from components.member1_didt.schemas.counterfactual import (
    CowState, InterventionScenario, SimulationRequest,
)
from components.member1_didt.simulation.biological_intervention_simulator import CounterfactualSimulator
from components.member1_didt.simulation.counterfactual_scenario import apply_scenario


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
    baseline, version, results, warnings = CounterfactualSimulator(predictor).run(
        baseline_state, [scenario()], 1,
    )
    result = results[0]
    assert baseline == pytest.approx(23)
    assert version == "synthetic-test-only"
    assert result.counterfactual_predicted_milk_yield_l_day == pytest.approx(23.2)
    assert result.absolute_yield_change_l_day == pytest.approx(.2)
    assert result.percentage_yield_change == pytest.approx(.2 / 23 * 100)
    assert result.scenario_status == "ESTIMATED_MODEL_INPUT_PERTURBATION"
    assert len(predictor.states) == 2
    assert predictor.states[0].thi_mean == 70 and predictor.states[1].thi_mean == 68
    assert baseline_state.thi_mean == 70
    assert not warnings


def test_multiple_scenarios_are_independent_and_original_state_is_unchanged():
    state = cow()
    predictor = FakePredictor()
    _, _, results, _ = CounterfactualSimulator(predictor).run(
        state, [scenario(value=68, scenario_id="first"), scenario(value=72, scenario_id="second")],
    )
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
    baseline, _, results, _ = CounterfactualSimulator(predictor).run(state, [intervention])

    result = results[0]
    assert baseline == 22.0
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
    with pytest.raises(Exception):
        scenario(**values)


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan")])
def test_request_rejects_invalid_milking_frequency_values(value):
    with pytest.raises(Exception):
        scenario(feature="milkings_per_day", value=value, category="management", unit="milkings/day")


def test_outside_training_support_is_reported_and_prediction_withheld():
    predictor = FakePredictor()
    _, _, results, _ = CounterfactualSimulator(predictor).run(cow(), [scenario(value=90)])
    assert results[0].scenario_status == "OUTSIDE_TRAINING_SUPPORT"
    assert results[0].counterfactual_predicted_milk_yield_l_day is None
    assert len(predictor.states) == 1


def test_missing_baseline_feature_missing_model_and_zero_baseline_are_explicit():
    predictor = FakePredictor()
    _, _, missing, _ = CounterfactualSimulator(predictor).run(cow(thi_mean=None), [scenario()])
    assert missing[0].scenario_status == "BASELINE_FEATURE_UNAVAILABLE"
    assert missing[0].counterfactual_predicted_milk_yield_l_day is None

    baseline, _, unavailable, warnings = CounterfactualSimulator(None).run(cow(), [scenario()])
    assert baseline is None and warnings
    assert unavailable[0].scenario_status == "PREDICTION_UNAVAILABLE"
    assert unavailable[0].counterfactual_predicted_milk_yield_l_day is None

    zero_predictor = FakePredictor(fn=lambda state: 0.0)
    _, _, zero, _ = CounterfactualSimulator(zero_predictor).run(cow(), [scenario()])
    assert zero[0].absolute_yield_change_l_day == 0
    assert zero[0].percentage_yield_change is None
    assert any("zero" in warning for warning in zero[0].warnings)


def test_failed_prediction_does_not_create_fallback_estimate():
    predictor = FakePredictor(fn=lambda state: (_ for _ in ()).throw(RuntimeError("private detail")))
    baseline, _, results, warnings = CounterfactualSimulator(predictor).run(cow(), [scenario()])
    assert baseline is None
    assert results[0].counterfactual_predicted_milk_yield_l_day is None
    assert results[0].scenario_status == "PREDICTION_UNAVAILABLE"
    assert "private detail" not in " ".join(warnings + results[0].warnings)


def test_request_validation_bounds_scenarios_and_values():
    with pytest.raises(Exception):
        SimulationRequest(animal_ref="x", scenarios=[scenario(value=float("nan"))])
    with pytest.raises(Exception):
        SimulationRequest(animal_ref="x", scenarios=[scenario(scenario_id=str(i)) for i in range(9)])
    with pytest.raises(Exception):
        SimulationRequest(animal_ref="x", scenarios=[scenario(scenario_id="same"), scenario(scenario_id="same")])


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
