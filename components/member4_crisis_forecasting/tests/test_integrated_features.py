"""Synthetic inputs only; no loader execution, network, or real-data training."""

from datetime import timedelta

import numpy as np
import pytest

from components.member4_crisis_forecasting.prediction.integrated_features import (
    FEATURE_NAMES, OPTIONAL_SIGNALS, integrated_features,
)
from components.member4_crisis_forecasting.prediction.feature_preprocessing import TrainingFeaturePreprocessor
from components.member4_crisis_forecasting.prediction.chronological_training import run_experiment
from components.member4_crisis_forecasting.tests.test_retrospective_training import START, aggregate, config


def integrated_rows(n=300):
    return [aggregate(i, thi_mean=60.0 + i % 10, thi_max=70.0 + i % 10,
                      hours_thi_above=float(i % 24), mastitis_episodes=i % 3,
                      udder_teat_episodes=i % 4, other_health_episodes=i % 5,
                      n_sessions=30 + i % 4, n_blood_alarms=i % 2,
                      n_conductivity_alarms=i % 3) for i in range(n)]


def feature_dict(rows, origin_index=7):
    values = integrated_features({row.date: row for row in rows}, START + timedelta(days=origin_index), "shipment")
    return dict(zip(FEATURE_NAMES, values))


def test_all_four_domains_and_separate_categories():
    rows = integrated_rows(15)
    result = feature_dict(rows)
    assert result["milk_per_cow_lag_1"] == rows[6].target_litres_per_cow
    assert result["milk_per_cow_lag_7"] == rows[0].target_litres_per_cow
    assert result["climate_thi_mean_7d"] == 63
    assert result["climate_thi_max_7d"] == 76
    assert result["climate_hours_thi_above_sum_7d"] == 21
    for field, name, operation in OPTIONAL_SIGNALS:
        expected = [getattr(row, field) for row in rows[:7]]
        expected = sum(expected) / 7 if operation == "mean" else max(expected) if operation == "max" else sum(expected)
        assert result[name] == expected
        assert result[f"{field}_observed_days_7d"] == 7
    assert len(FEATURE_NAMES) == len(set(FEATURE_NAMES)) == 29


@pytest.mark.parametrize("field,name,operation", OPTIONAL_SIGNALS)
def test_partial_auxiliary_history_is_missing_not_zero_or_partial_sum(field, name, operation):
    rows = integrated_rows(15)
    rows[3] = rows[3].model_copy(update={field: None})
    result = feature_dict(rows)
    assert np.isnan(result[name])
    assert result[f"{field}_observed_days_7d"] == 6


def test_recorded_zero_counts_and_hours_are_observed():
    rows = integrated_rows(15)
    for i in range(7):
        rows[i] = rows[i].model_copy(update={"mastitis_episodes": 0, "hours_thi_above": 0})
    values = feature_dict(rows)
    assert values["biological_mastitis_sum_7d"] == 0
    assert values["mastitis_episodes_observed_days_7d"] == 7
    assert values["climate_hours_thi_above_sum_7d"] == 0


def test_origin_future_values_and_all_scoreability_flags_cannot_enter_features():
    rows = integrated_rows(20)
    before = feature_dict(rows)
    changed = []
    for i, row in enumerate(rows):
        updates = {"is_scoreable": False}
        if i >= 7:
            updates.update({field: 0 for field, _, _ in OPTIONAL_SIGNALS})
            updates["target_litres_per_cow"] = 999
        changed.append(row.model_copy(update=updates))
    assert before == feature_dict(changed)


@pytest.mark.parametrize("change", ["gap", "milk_missing", "source_switch"])
def test_mandatory_milk_calendar_and_source_checks_remain(change):
    rows = integrated_rows(15)
    if change == "gap":
        rows.pop(0)
    elif change == "milk_missing":
        rows[0] = rows[0].model_copy(update={"target_litres_per_cow": None})
    else:
        rows[0] = rows[0].model_copy(update={"target_source": "delpro"})
    assert integrated_features({row.date: row for row in rows}, START + timedelta(days=7), "shipment") is None


def test_imputation_is_training_only_and_all_missing_features_are_dropped():
    prep = TrainingFeaturePreprocessor().fit(
        [[1, 10, np.nan], [3, np.nan, np.nan], [5, 30, np.nan]], ["milk", "health", "absent"],
    )
    assert prep.report()["dropped_all_missing_training_features"] == ["absent"]
    before = prep.imputer.statistics_.copy()
    values = prep.transform([[np.nan, np.nan, 99999]])
    assert values.tolist() == [[3, 20, 1, 1, 0]]
    np.testing.assert_array_equal(prep.imputer.statistics_, before)
    assert prep.output_names == ("milk", "health", "milk__missing", "health__missing", "absent__missing")


def test_missing_first_seen_in_test_has_explicit_indicator():
    prep = TrainingFeaturePreprocessor().fit([[1, 10], [3, 30]], ["milk", "health"])
    assert prep.transform([[2, np.nan]]).tolist() == [[2, 20, 0, 1]]


def test_integrated_training_reports_accuracy_importance_and_coverage():
    rows = integrated_rows()
    rows[40] = rows[40].model_copy(update={"n_blood_alarms": None})
    result = run_experiment(rows, config(class_weight="balanced_subsample", threshold_selection="validation_f1"), data_kind="synthetic")
    assert result["status"] == "evaluated_retrospectively"
    assert set(result["models"]) == {"random_forest", "training_prior_baseline"}
    assert result["features"] == list(FEATURE_NAMES)
    importance = result["feature_importance"]["values"]
    assert set(importance) == set(result["preprocessing"]["output_feature_names"])
    assert sum(importance.values()) == pytest.approx(1)
    assert result["feature_coverage"]["train"]["operational_blood_alarms_sum_7d"]["missing_samples"] > 0
    assert 0 <= result["reference_models"]["random_forest"]["test"]["accuracy"] <= 1
    if result["threshold_selection"]["random_forest"]["selected_threshold"] is None:
        assert result["models"]["random_forest"]["test"] == {"status": "no_warning_policy", "metrics": None}
    else:
        assert 0 <= result["models"]["random_forest"]["test"]["accuracy"] <= 1
    assert result["test_period_status"] == "exploratory_not_untouched_final"


def test_entirely_absent_domains_are_reported_without_imputed_zero_values():
    result = run_experiment([aggregate(i) for i in range(300)], config(), data_kind="synthetic")
    dropped = result["preprocessing"]["dropped_all_missing_training_features"]
    assert set(dropped) == {name for _, name, _ in OPTIONAL_SIGNALS}
    assert all(name not in result["feature_importance"]["values"] for name in dropped)


def test_preprocessor_is_fit_once_on_training_rows_only(monkeypatch):
    observed = []
    original = TrainingFeaturePreprocessor.fit
    def spy(self, x, names):
        observed.append(len(x))
        return original(self, x, names)
    monkeypatch.setattr(TrainingFeaturePreprocessor, "fit", spy)
    result = run_experiment(integrated_rows(), config(), data_kind="synthetic")
    assert observed == [result["splits"]["train"]["n"]]


def test_test_domain_changes_cannot_change_training_importance_or_thresholds():
    rows = integrated_rows()
    cfg = config(threshold_selection="validation_f1")
    first = run_experiment(rows, cfg, data_kind="synthetic")
    changed = [row.model_copy(update={field: None for field, _, _ in OPTIONAL_SIGNALS})
               if row.date > cfg.validation_end else row for row in rows]
    second = run_experiment(changed, cfg, data_kind="synthetic")
    assert first["threshold_selection"] == second["threshold_selection"]
    assert first["feature_importance"] == second["feature_importance"]
    assert first["preprocessing"] == second["preprocessing"]
