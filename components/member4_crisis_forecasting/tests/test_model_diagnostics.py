"""Synthetic probability arrays only; no database or real-data training."""

import numpy as np
import pytest

from components.member4_crisis_forecasting.prediction.decision_threshold import select_warning_policy
from components.member4_crisis_forecasting.prediction.model_diagnostics import decline_probabilities, probability_distribution
from components.member4_crisis_forecasting.prediction.chronological_training import ExperimentConfig, run_experiment
from components.member4_crisis_forecasting.tests.test_retrospective_training import aggregate, config


@pytest.mark.parametrize("value", [0, 0.005, 1])
def test_collapsed_probabilities_cannot_become_a_useful_warning_policy(value):
    policy = select_warning_policy([0, 0, 0, 1], [value] * 4, .5)
    assert policy["selected_threshold"] is None
    assert policy["status"] == "no_meaningful_validation_warning_policy"


def test_fine_grid_detects_separation_below_point_zero_one():
    result = select_warning_policy([0, 0, 1, 1], [.001, .001, .004, .005], .5)
    assert 0 < result["selected_threshold"] < .01
    assert result["best_validation_f1"] == 1
    assert all(row["threshold"] > 0 for row in result["validation_tradeoffs"])
    assert all(0 < row["predicted_positives"] < 4 for row in result["validation_tradeoffs"] if row["eligible"])


def test_some_alerts_without_discrimination_do_not_pass_baseline_checks():
    result = select_warning_policy([1, 0, 0, 1], [.1, .9, .8, .2], .5)
    assert result["selected_threshold"] is None


@pytest.mark.parametrize("y,p", [([], []), ([0, 0], [.1, .2]), ([1, 1], [.1, .2])])
def test_single_class_validation_does_not_create_a_policy(y, p):
    assert select_warning_policy(y, p, .5)["selected_threshold"] is None


def test_class_one_probability_is_selected_by_class_label_not_column_position():
    class ReversedClassifier:
        classes_ = np.array([1, 0])
        def predict_proba(self, x): return np.array([[.8, .2], [.1, .9]])
    assert decline_probabilities(ReversedClassifier(), [[0], [1]]).tolist() == [.8, .1]


def test_missing_positive_class_is_rejected():
    class SingleClass:
        classes_ = np.array([0])
    with pytest.raises(ValueError, match="expected_binary"):
        decline_probabilities(SingleClass(), [[0]])


def test_probability_diagnostics_are_aggregates_only():
    result = probability_distribution([0, 0, 1, 1], [0, .001, .004, .005])
    assert result["all"]["zero_count"] == 1
    assert result["decline"]["n"] == 2
    assert sum(result["all"]["histogram_counts"]) == 4
    assert set(result) == {"all", "normal", "decline"}
    assert "probabilities" not in result["all"]


def test_predefined_comparison_never_uses_test_to_select_settings():
    rows = [aggregate(i) for i in range(300)]
    cfg = config(forest_comparison="validation_small", threshold_selection="validation_f1")
    first = run_experiment(rows, cfg, data_kind="synthetic")
    altered = [row.model_copy(update={"target_litres_per_cow": 99}) if row.date > cfg.validation_end else row
               for row in rows]
    second = run_experiment(altered, cfg, data_kind="synthetic")
    assert first["selected_forest"] == second["selected_forest"]
    assert first["forest_validation_comparison"] == second["forest_validation_comparison"]
    assert first["threshold_selection"] == second["threshold_selection"]
    assert len(first["forest_validation_comparison"]) == 3
    assert all("test_probabilities" not in result for result in first["forest_validation_comparison"].values())


def test_comparison_requires_safe_validation_policy_selection():
    with pytest.raises(ValueError, match="requires_safe_validation"):
        config(forest_comparison="validation_small", threshold_selection="fixed")


def test_legacy_mode_is_preserved_and_explicitly_not_a_warning_policy():
    result = run_experiment([aggregate(i) for i in range(300)], config(threshold_selection="validation_f1_legacy"), data_kind="synthetic")
    assert result["selected_forest"] == "reference"
    assert result["threshold_selection"]["random_forest"]["warning_policy_status"].startswith("legacy_reproduction")


def test_no_meaningful_policy_reports_null_metrics_not_all_alert_success(monkeypatch):
    import components.member4_crisis_forecasting.prediction.chronological_training as training
    def collapsed(model, x): return np.zeros(len(x))
    monkeypatch.setattr(training, "decline_probabilities", collapsed)
    result = run_experiment([aggregate(i) for i in range(300)], config(threshold_selection="validation_f1"), data_kind="synthetic")
    assert result["warning_policy_status"] == "no_meaningful_validation_warning_policy"
    assert result["models"]["random_forest"]["test"] == {"status": "no_warning_policy", "metrics": None}
    assert result["reference_models"]["random_forest"]["test"]["predicted_positives"] == 0
