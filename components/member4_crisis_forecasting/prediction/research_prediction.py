"""Inference-only historical research output; never fit, select, or recalibrate."""

from collections import Counter
from datetime import date, timedelta
import hashlib
from pathlib import Path
import pickle
import platform
import warnings
from statistics import fmean
from typing import Literal
from uuid import UUID, uuid4

import numpy as np
import sklearn
from pydantic import AwareDatetime, Field, model_validator
from sklearn.ensemble import RandomForestClassifier
from sklearn.exceptions import InconsistentVersionWarning

from components.member4_crisis_forecasting.schemas.risk_output import ResearchModel
from components.member4_crisis_forecasting.prediction.chronological_training import ExperimentConfig, split_name
from components.member4_crisis_forecasting.prediction.model_artifact import ARTIFACT_KEYS, feature_definitions
from components.member4_crisis_forecasting.prediction.feature_preprocessing import TrainingFeaturePreprocessor
from components.member4_crisis_forecasting.prediction.integrated_features import FEATURE_NAMES as INTEGRATED_NAMES, integrated_features
from components.member4_crisis_forecasting.prediction.historical_features import FEATURE_NAMES as PRODUCTION_NAMES, production_features
from components.member4_crisis_forecasting.prediction.model_diagnostics import decline_probabilities
from components.member4_crisis_forecasting.prediction.retrospective import retrospective_targets
from components.member4_crisis_forecasting.prediction.decline_target import DeclineTargetConfig


def validate_prediction_artifact(bundle):
    if not isinstance(bundle, dict) or set(bundle) != ARTIFACT_KEYS or bundle["artifact_version"] != "1.0.0":
        raise ValueError("unsupported_model_artifact")
    metadata = bundle["research_metadata"]
    if (metadata["model_status"] != "random_forest_experimental_not_live_validated"
            or metadata["research_only"] is not True or metadata["live_warning_allowed"] is not False):
        raise ValueError("research_only_artifact_required")
    cfg = ExperimentConfig.model_validate(bundle["configuration"])
    names = INTEGRATED_NAMES if cfg.feature_set == "integrated" else PRODUCTION_NAMES
    if tuple(bundle["raw_feature_order"]) != tuple(names) or bundle["feature_definitions"] != feature_definitions(names):
        raise ValueError("artifact_feature_definition_or_order_mismatch")
    preprocessing = bundle["preprocessing"]
    if cfg.feature_set == "integrated":
        if (not isinstance(preprocessing, TrainingFeaturePreprocessor)
                or tuple(preprocessing.feature_names) != tuple(names)
                or tuple(preprocessing.output_names) != tuple(bundle["transformed_feature_order"])):
            raise ValueError("artifact_preprocessing_mismatch")
    elif preprocessing is not None or tuple(bundle["transformed_feature_order"]) != tuple(names):
        raise ValueError("artifact_identity_preprocessing_mismatch")
    model = bundle["model"]
    if (not isinstance(model, RandomForestClassifier) or not hasattr(model, "estimators_")
            or model.n_features_in_ != len(bundle["transformed_feature_order"])):
        raise ValueError("fitted_forest_feature_alignment_required")
    if model.get_params(deep=False) != bundle["forest_parameters"]:
        raise ValueError("saved_forest_parameters_mismatch")
    threshold = bundle["decision_policy"]["selected_threshold"]
    if threshold is not None and (not np.isfinite(threshold) or not 0 <= threshold <= 1):
        raise ValueError("invalid_saved_decision_threshold")
    return cfg


def load_trusted_artifact(path, *, trust_local_artifact=False):
    """USER-RUN ONLY. Pickle can execute code: trust must be established beforehand."""
    if not trust_local_artifact:
        raise PermissionError("explicit_trusted_local_pickle_acknowledgement_required")
    path = Path(path).expanduser().resolve()
    if path.suffix.lower() != ".pkl" or path.is_relative_to(Path(__file__).resolve().parents[3]):
        raise ValueError("private_local_pkl_outside_repository_required")
    serialized = path.read_bytes()
    with warnings.catch_warnings():
        warnings.simplefilter("error", InconsistentVersionWarning)
        bundle = pickle.loads(serialized)
    validate_prediction_artifact(bundle)
    expected = {"python": platform.python_version(), "scikit_learn": sklearn.__version__, "numpy": np.__version__}
    if bundle["software_versions"] != expected:
        raise ValueError("artifact_software_versions_must_match")
    return bundle, hashlib.sha256(serialized).hexdigest()


class ResearchPrediction(ResearchModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    prediction_id: UUID
    farm_id: Literal["FARM_X"] = "FARM_X"
    assessment_date: date
    generated_at: AwareDatetime
    artifact_version: Literal["1.0.0"] = "1.0.0"
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_status: Literal["random_forest_experimental_not_live_validated"] = "random_forest_experimental_not_live_validated"
    research_only: Literal[True] = True
    live_warning_allowed: Literal[False] = False
    predicted_decline_probability: float = Field(ge=0, le=1)
    probability_interpretation: Literal["uncalibrated_experimental_model_score"] = "uncalibrated_experimental_model_score"
    saved_threshold: float | None = Field(ge=0, le=1)
    predicted_decline: bool | None
    classification_status: Literal["no_saved_threshold", "experimental_classification", "legacy_not_warning_policy"]
    actual_outcome: bool | None
    outcome_reason: str
    experiment_partition: Literal["train_in_sample", "validation_model_selection", "test_exploratory", "post_experiment_research"]
    milk_source: Literal["shipment", "delpro"]
    configuration: ExperimentConfig
    historical_availability: Literal["unknown"] = "unknown"
    recording_completeness: Literal["unknown"] = "unknown"

    @model_validator(mode="after")
    def consistent_prediction(self):
        if self.assessment_date > self.generated_at.date() or self.milk_source != self.configuration.milk_source:
            raise ValueError("prediction_date_or_source_mismatch")
        if self.saved_threshold is None:
            if self.predicted_decline is not None or self.classification_status != "no_saved_threshold":
                raise ValueError("missing_threshold_cannot_classify")
        elif self.predicted_decline != (self.predicted_decline_probability >= self.saved_threshold):
            raise ValueError("classification_threshold_mismatch")
        else:
            status = ("legacy_not_warning_policy" if self.saved_threshold == 0 or
                      self.configuration.threshold_selection == "validation_f1_legacy" else "experimental_classification")
            if self.classification_status != status:
                raise ValueError("classification_status_mismatch")
        partition = split_name(self.assessment_date, self.assessment_date + timedelta(days=7), self.configuration)
        if partition is None and self.assessment_date <= self.configuration.test_end:
            raise ValueError("original_purge_boundary_cannot_be_published")
        expected = {"train": "train_in_sample", "validation": "validation_model_selection",
                    "test": "test_exploratory", None: "post_experiment_research"}[partition]
        if self.experiment_partition != expected:
            raise ValueError("original_partition_mismatch")
        if (self.actual_outcome is not None) != (self.outcome_reason == "retrospective_snapshot_target"):
            raise ValueError("outcome_status_mismatch")
        return self


def predict_research_history(rows, bundle, artifact_sha256, *, start_date, end_date, generated_at, data_kind):
    cfg = validate_prediction_artifact(bundle)
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("timezone_aware_generation_time_required")
    if data_kind != bundle["research_metadata"]["data_kind"] or start_date > end_date:
        raise ValueError("artifact_data_kind_or_date_range_mismatch")
    by_date = {row.date: row for row in rows}
    if len(by_date) != len(rows):
        raise ValueError("duplicate_dates")
    builder = integrated_features if cfg.feature_set == "integrated" else production_features
    excluded, pending, vectors = Counter(), [], []
    for row in sorted(rows, key=lambda item: item.date):
        if not start_date <= row.date <= end_date:
            continue
        if row.date > generated_at.date():
            excluded["future_origin"] += 1
            continue
        if row.target_source != cfg.milk_source:
            excluded["different_or_missing_milk_source"] += 1
            continue
        if not row.is_scoreable or row.target_litres_per_cow is None:
            excluded["origin_ineligible"] += 1
            continue
        # Match historical training reference eligibility without looking ahead.
        history = [by_date.get(row.date - timedelta(days=lag)) for lag in range(1, 8)]
        if any(day is None or not day.is_scoreable for day in history):
            excluded["historical_reference_ineligible_or_missing"] += 1
            continue
        if all(day.target_litres_per_cow is not None for day in history) and sum(day.target_litres_per_cow for day in history) <= 0:
            excluded["nonpositive_historical_baseline"] += 1
            continue
        partition = split_name(row.date, row.date + timedelta(days=7), cfg)
        if partition is None and row.date <= cfg.test_end:
            excluded["original_purge_boundary"] += 1
            continue
        features = builder(by_date, row.date, cfg.milk_source)
        if features is None:
            excluded["unavailable_historical_features"] += 1
            continue
        pending.append((row.date, {"train": "train_in_sample", "validation": "validation_model_selection",
                                  "test": "test_exploratory", None: "post_experiment_research"}[partition]))
        vectors.append(features)
    # Outcomes are attached separately AFTER feature eligibility. Missing outcomes
    # never become negatives or decide whether an otherwise eligible score exists.
    outcome_rows = [row for row in rows if row.date <= generated_at.date()]
    outcomes = {target.origin: target for target in retrospective_targets(outcome_rows, cfg.milk_source,
                DeclineTargetConfig(decline_threshold_pct=cfg.decline_threshold_pct))}
    outputs = []
    if vectors:
        transformed = bundle["preprocessing"].transform(vectors) if bundle["preprocessing"] is not None else vectors
        probabilities = decline_probabilities(bundle["model"], transformed)
        threshold = bundle["decision_policy"]["selected_threshold"]
        status = ("no_saved_threshold" if threshold is None else "legacy_not_warning_policy"
                  if threshold == 0 or cfg.threshold_selection == "validation_f1_legacy" else "experimental_classification")
        for (origin, partition), probability in zip(pending, probabilities):
            outcome = outcomes.get(origin)
            outputs.append(ResearchPrediction(
                prediction_id=uuid4(), assessment_date=origin, generated_at=generated_at,
                artifact_sha256=artifact_sha256, predicted_decline_probability=float(probability),
                saved_threshold=threshold, predicted_decline=None if threshold is None else bool(probability >= threshold),
                classification_status=status, actual_outcome=outcome.label if outcome else None,
                outcome_reason=outcome.reason if outcome else "outcome_unavailable",
                experiment_partition=partition, milk_source=cfg.milk_source, configuration=cfg,
            ))
    p = [item.predicted_decline_probability for item in outputs]
    summary = dict(status="retrospective_research_predictions_verified", predictions=len(outputs),
        research_only=True, live_warning_allowed=False, model_status="random_forest_experimental_not_live_validated",
        artifact_version=bundle["artifact_version"], artifact_sha256=artifact_sha256,
        historical_availability="unknown", recording_completeness="unknown",
        probability_interpretation="uncalibrated_experimental_model_score",
        probability_summary=dict(n=len(p), mean=fmean(p) if p else None, min=min(p) if p else None, max=max(p) if p else None),
        classification_counts=dict(Counter(item.classification_status for item in outputs)),
        experimental_decline_classifications=sum(item.predicted_decline is True for item in outputs),
        actual_outcome_counts=dict(available=sum(item.actual_outcome is not None for item in outputs),
                                  positives=sum(item.actual_outcome is True for item in outputs),
                                  unavailable=sum(item.actual_outcome is None for item in outputs)),
        partition_counts=dict(Counter(item.experiment_partition for item in outputs)), excluded=dict(excluded),
        notes=["Training predictions are in-sample; validation selected the model/policy; original test remains exploratory.",
               "Post-experiment scores are retrospective research, not live-validated forecasts or calibrated risks.",
               "Future actuals are outcome annotations only; no model fitting or threshold selection occurs."])
    return tuple(outputs), summary
