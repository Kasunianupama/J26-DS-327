"""Select a decision threshold from validation predictions only, never test data."""

import numpy as np


def select_validation_f1(actual, probabilities, reference_threshold):
    """Fixed 0.00..1.00 grid plus reference; ties choose the highest threshold.

    No held-out test arrays are accepted. Both classes are required. Empty or
    single-class validation falls back explicitly to the reference threshold.
    """
    y = np.asarray(actual)
    p = np.asarray(probabilities, dtype=float)
    if (y.ndim != 1 or p.ndim != 1 or len(y) != len(p)
            or not np.isin(y, [0, 1]).all() or not np.isfinite(p).all()
            or ((p < 0) | (p > 1)).any()
            or not np.isfinite(reference_threshold) or not 0 < reference_threshold < 1):
        raise ValueError("invalid_validation_threshold_inputs")
    result = dict(method="validation_f1", reference_threshold=float(reference_threshold),
                  selected_threshold=float(reference_threshold), validation_tradeoffs=[])
    if len(y) == 0 or len(np.unique(y)) != 2:
        result["status"] = "unavailable_validation_requires_both_classes_reference_used"
        return result
    candidates = sorted({i / 100 for i in range(101)} | {float(reference_threshold)})
    best = (-1.0, -1.0)
    for threshold in candidates:
        predicted = p >= threshold
        tp = int(((y == 1) & predicted).sum())
        fp = int(((y == 0) & predicted).sum())
        fn = int(((y == 1) & ~predicted).sum())
        f1 = 2 * tp / (2 * tp + fp + fn)
        result["validation_tradeoffs"].append(dict(
            threshold=threshold, precision=tp / (tp + fp) if tp + fp else None,
            recall=tp / (tp + fn), f1=f1, predicted_positives=tp + fp,
        ))
        if (f1, threshold) > best:
            best = (f1, threshold)
    result.update(status="selected_on_validation_only", selected_threshold=best[1],
                  best_validation_f1=best[0], tie_break="highest_threshold")
    return result


def select_warning_policy(actual, probabilities, reference_threshold):
    """Validation-only F1 subject to nondegeneracy and naive-baseline checks.

    Fine PREDECLARED grid below .01 avoids the legacy 0/.01 blind spot. These
    criteria are research sanity checks, not a validated clinical alert policy.
    """
    # Reuse legacy input validation, but never use its selected threshold.
    select_validation_f1(actual, probabilities, reference_threshold)
    y, p = np.asarray(actual), np.asarray(probabilities, dtype=float)
    result = dict(method="validation_f1_nondegenerate", selected_threshold=None,
                  reference_threshold=reference_threshold, validation_tradeoffs=[],
                  status="no_meaningful_validation_warning_policy")
    if len(y) == 0 or len(np.unique(y)) != 2:
        result["status"] = "insufficient_validation_classes_no_warning_policy"
        return result
    prevalence = float(y.mean())
    all_alert_f1 = 2 * prevalence / (1 + prevalence)
    result.update(validation_prevalence=prevalence, all_alert_f1=all_alert_f1)
    grid = sorted({i / 10000 for i in range(1, 100)} | {i / 100 for i in range(1, 101)} | {reference_threshold})
    best = None
    for threshold in grid:
        alert = p >= threshold
        tp, fp = int(((y == 1) & alert).sum()), int(((y == 0) & alert).sum())
        fn = int(((y == 1) & ~alert).sum())
        precision = tp / (tp + fp) if tp + fp else None
        recall, f1 = tp / (tp + fn), 2 * tp / (2 * tp + fp + fn)
        eligible = (0 < int(alert.sum()) < len(y) and tp > 0
                    and precision > prevalence and f1 > all_alert_f1)
        result["validation_tradeoffs"].append(dict(threshold=threshold, precision=precision,
            recall=recall, f1=f1, predicted_positives=int(alert.sum()), eligible=eligible))
        rank = (f1, precision if precision is not None else -1, threshold)
        if eligible and (best is None or rank > best):
            best = rank
    if best is not None:
        result.update(status="selected_on_validation_only_not_operationally_validated",
                      selected_threshold=best[2], best_validation_f1=best[0],
                      selected_validation_precision=best[1], tie_break="precision_then_highest_threshold")
    return result
