"""Chronological retrospective comparison; optional caller-provided artifact sink."""

from collections import Counter
from datetime import date
from typing import Literal

import numpy as np
import sklearn
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import average_precision_score, confusion_matrix, precision_recall_fscore_support

from components.member4_crisis_forecasting.prediction.decline_target import DeclineTargetConfig
from components.member4_crisis_forecasting.prediction.retrospective import retrospective_targets
from components.member4_crisis_forecasting.prediction.historical_features import FEATURE_NAMES, production_features
from components.member4_crisis_forecasting.prediction.decision_threshold import select_validation_f1, select_warning_policy
from components.member4_crisis_forecasting.prediction.model_diagnostics import decline_probabilities, probability_distribution
from components.member4_crisis_forecasting.prediction.integrated_features import (
    FEATURE_NAMES as INTEGRATED_FEATURE_NAMES, integrated_features,
)
from components.member4_crisis_forecasting.prediction.feature_preprocessing import TrainingFeaturePreprocessor, feature_coverage


class ExperimentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    milk_source: Literal["shipment", "delpro"]
    decline_threshold_pct: float = Field(gt=0, le=100, allow_inf_nan=False)
    decision_threshold: float = Field(gt=0, lt=1, allow_inf_nan=False)
    train_end: date
    validation_end: date
    test_end: date
    min_train_samples: int = Field(default=30, ge=2, strict=True)
    class_weight: Literal["balanced_subsample"] | None = None
    threshold_selection: Literal["fixed", "validation_f1", "validation_f1_legacy"] = "fixed"
    feature_set: Literal["integrated", "production_only"] = "integrated"
    forest_comparison: Literal["fixed", "validation_small"] = "fixed"

    @model_validator(mode="after")
    def ordered_boundaries(self):
        if not self.train_end < self.validation_end < self.test_end:
            raise ValueError("split_dates_must_increase")
        if self.forest_comparison == "validation_small" and self.threshold_selection != "validation_f1":
            raise ValueError("forest_comparison_requires_safe_validation_f1")
        return self


def split_name(origin: date, outcome_end: date, config: ExperimentConfig) -> str | None:
    """Purge origins whose seven-day outcomes cross their split end date."""
    if origin <= config.train_end:
        return "train" if outcome_end <= config.train_end else None
    if origin <= config.validation_end:
        return "validation" if outcome_end <= config.validation_end else None
    if origin <= config.test_end:
        return "test" if outcome_end <= config.test_end else None
    return None


def classification_metrics(actual, probabilities, threshold):
    """None for undefined metrics; PR-AUC is reported specifically as AP."""
    actual = np.asarray(actual, dtype=int)
    probabilities = np.asarray(probabilities, dtype=float)
    predicted = (probabilities >= threshold).astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(
        actual, predicted, average="binary", zero_division=0,
    )
    positives, alerts = int(actual.sum()), int(predicted.sum())
    return dict(
        n=len(actual), positives=positives, negatives=len(actual) - positives,
        positive_fraction=positives / len(actual) if len(actual) else None,
        predicted_positives=alerts,
        accuracy=float((actual == predicted).mean()) if len(actual) else None,
        precision=float(precision) if alerts else None,
        recall=float(recall) if positives else None,
        f1=float(f1) if positives + alerts else None,
        confusion_matrix=confusion_matrix(actual, predicted, labels=[0, 1]).tolist(),
        pr_auc_average_precision=float(average_precision_score(actual, probabilities))
        if 0 < positives < len(actual) else None,
    )


def run_experiment(rows, config: ExperimentConfig, *, data_kind: Literal["synthetic", "published"], artifact_callback=None):
    """Never tune on test or refit on validation. Return aggregates only.

    min_train_samples is a computational guard, not scientific sample adequacy.
    The sole learned model is a fixed, reproducible Random Forest classifier.
    Optional artifact_callback receives only the already-selected fitted model
    bundle after evaluation; the ordinary summary return value is unchanged.
    """
    if data_kind not in {"synthetic", "published"}:
        raise ValueError("invalid_data_kind")
    by_date = {row.date: row for row in rows}
    if len(by_date) != len(rows):
        raise ValueError("duplicate_dates")
    targets = retrospective_targets(rows, config.milk_source, DeclineTargetConfig(
        decline_threshold_pct=config.decline_threshold_pct,
    ))
    exclusion = Counter()
    feature_names = INTEGRATED_FEATURE_NAMES if config.feature_set == "integrated" else FEATURE_NAMES
    builder = integrated_features if config.feature_set == "integrated" else production_features
    splits = {name: ([], []) for name in ("train", "validation", "test")}
    for target in targets:
        if target.label is None:
            exclusion[target.reason] += 1
            continue
        partition = split_name(target.origin, target.outcome_end, config)
        if partition is None:
            exclusion["purged_or_outside_split_dates"] += 1
            continue
        features = builder(by_date, target.origin, config.milk_source)
        if features is None:
            exclusion["missing_or_invalid_lagged_features"] += 1
            continue
        splits[partition][0].append(features)
        splits[partition][1].append(int(target.label))
    summary = dict(
        experiment_version="c4-retrospective-5-diagnostic-comparison",
        software_versions={"scikit_learn": sklearn.__version__, "numpy": np.__version__},
        mode="retrospective_snapshot_research_only", data_kind=data_kind,
        historical_availability="unknown", recording_completeness="unknown",
        publication_version="unknown", config=config.model_dump(mode="json"),
        features=list(feature_names), excluded=dict(exclusion),
        feature_coverage={name: feature_coverage(x, feature_names) for name, (x, _) in splits.items()},
        test_period_status="exploratory_not_untouched_final",
        splits={name: dict(n=len(y), positives=sum(y), negatives=len(y) - sum(y),
                          positive_fraction=sum(y) / len(y) if y else None)
                for name, (_, y) in splits.items()},
        limitations=[
            "Observation-date lags do not prove point-in-time availability; delayed records and corrections may leak.",
            "ETL scoreability selects outcomes and may exclude genuine severe declines; it is not a feature.",
            "Overlapping outcomes are correlated; metrics describe daily origin labels, not independent crises.",
            "Multi-factor retrospective classification is not validated live forecasting or a composite Farm Risk Score.",
            "Health and alarm semantics/completeness are unverified; raw separate counts are not diagnoses or equipment failures.",
            "Missingness/coverage may encode changing recording practices; feature importance is not causal evidence.",
            "No operational deployment or calibrated probability claim is supported.",
            "Previously examined 2022 test results are exploratory; validation selection does not restore an untouched final test.",
        ],
    )
    x_train, y_train = splits["train"]
    if (len(y_train) < config.min_train_samples or len(set(y_train)) != 2
            or any(not splits[name][1] for name in ("validation", "test"))):
        summary.update(status="insufficient_data", models={})
        return summary
    preprocessing = None
    if config.feature_set == "integrated":
        preprocessing = TrainingFeaturePreprocessor().fit(x_train, feature_names)
        summary["preprocessing"] = preprocessing.report()
        splits = {name: (preprocessing.transform(x), y) for name, (x, y) in splits.items()}
        fitted_feature_names = preprocessing.output_names
    else:
        # Preserve the prior production-only experiment without extra indicators.
        summary["preprocessing"] = {"strategy": "none", "output_feature_names": list(feature_names)}
        fitted_feature_names = feature_names
    x_train, y_train = splits["train"]
    x_validation, y_validation = splits["validation"]
    candidates = [("reference", dict(max_depth=5, min_samples_leaf=5, class_weight=config.class_weight))]
    if config.forest_comparison == "validation_small":
        candidates.extend([
            ("weighted_regularized", dict(max_depth=4, min_samples_leaf=10, class_weight="balanced_subsample")),
            ("weighted_flexible", dict(max_depth=8, min_samples_leaf=2, class_weight="balanced_subsample")),
        ])
    fitted = []
    summary["forest_validation_comparison"] = {}
    for candidate_name, settings in candidates:
        candidate = RandomForestClassifier(n_estimators=200, max_features="sqrt", bootstrap=True,
                                          random_state=0, n_jobs=1, **settings)
        candidate.fit(x_train, y_train)
        if candidate.n_features_in_ != len(fitted_feature_names):
            raise ValueError("fitted_feature_alignment_mismatch")
        validation_p = decline_probabilities(candidate, x_validation)
        policy = select_warning_policy(y_validation, validation_p, config.decision_threshold)
        diagnostics = dict(settings=settings, policy=policy,
            train_probabilities=probability_distribution(y_train, decline_probabilities(candidate, x_train)),
            validation_probabilities=probability_distribution(y_validation, validation_p),
            train_reference_metrics=classification_metrics(y_train, decline_probabilities(candidate, x_train), config.decision_threshold),
            validation_reference_metrics=classification_metrics(y_validation, validation_p, config.decision_threshold))
        summary["forest_validation_comparison"][candidate_name] = diagnostics
        fitted.append((candidate_name, candidate, policy))
    chosen = fitted[0]
    if config.forest_comparison == "validation_small":
        eligible = [item for item in fitted if item[2]["selected_threshold"] is not None]
        if eligible:
            # Stable predefined order breaks equal model scores. Test is not inspected.
            chosen = max(eligible, key=lambda item: (item[2]["best_validation_f1"], item[2]["selected_validation_precision"]))
    summary["selected_forest"] = chosen[0]
    forest = chosen[1]
    # Fit only training rows. Tree inputs do not require standardization.
    summary["feature_importance"] = {
        "method": "random_forest_training_impurity_decrease_not_causal",
        "values": {name: float(value) for name, value in zip(fitted_feature_names, forest.feature_importances_)},
    }
    dummy = DummyClassifier(strategy="prior").fit(x_train, y_train)
    summary["models"] = {}
    summary["reference_models"] = {}
    summary["threshold_selection"] = {}
    for name, model in (("random_forest", forest), ("training_prior_baseline", dummy)):
        validation_probabilities = decline_probabilities(model, x_validation)
        selection = (
            select_warning_policy(y_validation, validation_probabilities, config.decision_threshold)
            if config.threshold_selection == "validation_f1" else
            select_validation_f1(y_validation, validation_probabilities, config.decision_threshold)
            if config.threshold_selection == "validation_f1_legacy" else dict(
                method="fixed", status="configured_reference_used",
                reference_threshold=config.decision_threshold,
                selected_threshold=config.decision_threshold, validation_tradeoffs=[],
            )
        )
        if config.threshold_selection == "validation_f1_legacy":
            selection["warning_policy_status"] = "legacy_reproduction_not_a_validated_warning_policy"
        summary["threshold_selection"][name] = selection
        # Freeze the threshold before obtaining test predictions. No test labels
        # or probabilities enter selection; no estimator is refit afterward.
        threshold = selection["selected_threshold"]
        predictions = {"validation": validation_probabilities,
                       "test": decline_probabilities(model, splits["test"][0])}
        summary["models"][name] = {
            partition: classification_metrics(splits[partition][1], probabilities, threshold) if threshold is not None
            else {"status": "no_warning_policy", "metrics": None}
            for partition, probabilities in predictions.items()
        }
        summary["reference_models"][name] = {
            partition: classification_metrics(splits[partition][1], probabilities, config.decision_threshold)
            for partition, probabilities in predictions.items()
        }
    summary["status"] = "evaluated_retrospectively"
    summary["warning_policy_status"] = (
        "legacy_reproduction_only_not_a_warning_policy" if config.threshold_selection == "validation_f1_legacy" else
        "no_meaningful_validation_warning_policy" if summary["threshold_selection"]["random_forest"]["selected_threshold"] is None
        else "research_policy_only_not_live_validated"
    )
    if artifact_callback is not None:
        from components.member4_crisis_forecasting.prediction.model_artifact import create_model_artifact
        artifact_callback(create_model_artifact(
            model=forest, preprocessing=preprocessing, raw_feature_names=feature_names,
            transformed_feature_names=fitted_feature_names, config=config, summary=summary,
        ))
    return summary
