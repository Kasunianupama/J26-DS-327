"""Aggregate-only diagnostics and explicit class-to-probability alignment."""

import numpy as np


def decline_probabilities(model, x):
    classes = list(model.classes_)
    if classes.count(1) != 1 or set(classes) != {0, 1}:
        raise ValueError("expected_binary_normal_0_decline_1_classes")
    probabilities = np.asarray(model.predict_proba(x), dtype=float)
    if (probabilities.ndim != 2 or probabilities.shape != (len(x), len(classes))
            or not np.isfinite(probabilities).all()
            or ((probabilities < 0) | (probabilities > 1)).any()
            or not np.allclose(probabilities.sum(axis=1), 1)):
        raise ValueError("invalid_classifier_probabilities")
    return probabilities[:, classes.index(1)]


def probability_distribution(actual, probabilities):
    """Fixed-bin counts and quantiles only; no sample arrays are returned."""
    y, p = np.asarray(actual), np.asarray(probabilities, dtype=float)
    def describe(values):
        edges = [0, 0.0001, 0.001, 0.01, 0.05, 0.1, 0.25, 0.5, 1]
        return dict(n=len(values), zero_count=int((values == 0).sum()), distinct_score_count=len(np.unique(values)),
                    mean=float(values.mean()) if len(values) else None,
                    quantiles=dict(zip(("min", "q25", "median", "q75", "max"),
                                       map(float, np.quantile(values, [0, .25, .5, .75, 1])))) if len(values) else None,
                    histogram_edges=edges, histogram_counts=np.histogram(values, bins=edges)[0].tolist())
    return {"all": describe(p), "normal": describe(p[y == 0]), "decline": describe(p[y == 1])}
