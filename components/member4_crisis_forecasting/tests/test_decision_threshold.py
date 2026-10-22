"""Synthetic labels/probabilities only; no database or filesystem access."""

import pytest

from components.member4_crisis_forecasting.prediction.decision_threshold import select_validation_f1


def test_validation_f1_can_select_below_half_with_precision_recall_tradeoffs():
    result = select_validation_f1([0, 0, 1, 1], [0.01, 0.02, 0.2, 0.3], 0.5)
    assert result["selected_threshold"] == 0.2
    assert result["best_validation_f1"] == 1
    selected = next(row for row in result["validation_tradeoffs"] if row["threshold"] == 0.2)
    assert selected["precision"] == selected["recall"] == 1
    reference = next(row for row in result["validation_tradeoffs"] if row["threshold"] == 0.5)
    assert reference["predicted_positives"] == 0
    assert reference["recall"] == 0


def test_equal_f1_ties_use_highest_threshold_and_inclusive_boundary():
    result = select_validation_f1([0, 1], [0.1, 0.9], 0.5)
    assert result["selected_threshold"] == 0.9
    assert result == select_validation_f1([0, 1], [0.1, 0.9], 0.5)


@pytest.mark.parametrize("actual,probabilities", [([], []), ([0, 0], [0.1, 0.2]), ([1, 1], [0.1, 0.2])])
def test_single_class_or_empty_validation_uses_explicit_reference_fallback(actual, probabilities):
    result = select_validation_f1(actual, probabilities, 0.5)
    assert result["selected_threshold"] == 0.5
    assert result["status"].startswith("unavailable_validation")
    assert result["validation_tradeoffs"] == []


@pytest.mark.parametrize("probability,expected", [(0, 0), (1, 1), (0.05, 0.05)])
def test_constant_dummy_probabilities_allow_all_or_no_alerts(probability, expected):
    result = select_validation_f1([0, 0, 0, 1], [probability] * 4, 0.5)
    assert result["selected_threshold"] == expected
    assert result["best_validation_f1"] == pytest.approx(0.4)


def test_imbalanced_validation_does_not_optimize_accuracy():
    result = select_validation_f1([0] * 99 + [1], [0.01] * 99 + [0.2], 0.5)
    assert result["selected_threshold"] == 0.2
    assert result["best_validation_f1"] == 1


@pytest.mark.parametrize("actual,probabilities,reference", [
    ([0, 1], [0.2], 0.5), ([0, 2], [0.1, 0.2], 0.5),
    ([0, 1], [float("nan"), 0.2], 0.5), ([0, 1], [-0.1, 0.2], 0.5),
    ([0, 1], [0.1, 1.1], 0.5), ([0, 1], [0.1, 0.2], 0),
    ([[0, 1]], [[0.1, 0.2]], 0.5),
])
def test_invalid_inputs_fail_safely(actual, probabilities, reference):
    with pytest.raises(ValueError, match="invalid_validation_threshold_inputs"):
        select_validation_f1(actual, probabilities, reference)


def test_reference_threshold_is_included_even_outside_grid():
    result = select_validation_f1([0, 1], [0.2, 0.205], 0.205)
    assert result["selected_threshold"] == 0.205
