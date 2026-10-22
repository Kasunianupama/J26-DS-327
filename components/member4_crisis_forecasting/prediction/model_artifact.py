"""Opt-in private local persistence of an already fitted research forest."""

from datetime import datetime, timezone
from pathlib import Path
import pickle
import platform

from sklearn.ensemble import RandomForestClassifier

from components.member4_crisis_forecasting.prediction.integrated_features import OPTIONAL_SIGNALS

ARTIFACT_KEYS = {
    "artifact_version", "created_at", "model", "preprocessing", "raw_feature_order",
    "transformed_feature_order", "feature_definitions", "configuration", "selected_forest",
    "forest_parameters", "decision_policy", "research_metadata", "software_versions",
}


def feature_definitions(names):
    descriptions = {
        "last_per_cow": "Per-cow production on t-1.",
        "mean_7d": "Arithmetic mean per-cow production over t-7..t-1.",
        "std_7d": "Population standard deviation per-cow production over t-7..t-1.",
        "recent_minus_earlier_mean": "Mean t-3..t-1 minus mean t-7..t-4 per-cow production.",
    }
    for lag in range(1, 8):
        descriptions[f"milk_per_cow_lag_{lag}"] = f"Per-cow production on t-{lag}."
    for field, name, operation in OPTIONAL_SIGNALS:
        descriptions[name] = f"{operation} of {field} over t-7..t-1; missing if any of seven values is absent."
        descriptions[f"{field}_observed_days_7d"] = f"Number of nonmissing {field} observations over t-7..t-1; zero is observed."
    if not set(names) <= set(descriptions):
        raise ValueError("unknown_artifact_feature_definition")
    return dict(version="c4-lagged-features-1", window="t-7..t-1_only",
                builder="integrated_features" if len(names) > 4 else "production_features",
                features=[dict(name=name, definition=descriptions[name]) for name in names])


def create_model_artifact(*, model, preprocessing, raw_feature_names, transformed_feature_names, config, summary):
    """Allowlist only: never accept rows, feature matrices, labels or credentials."""
    if not isinstance(model, RandomForestClassifier) or not hasattr(model, "estimators_"):
        raise ValueError("fitted_random_forest_required")
    if model.n_features_in_ != len(transformed_feature_names):
        raise ValueError("artifact_feature_alignment_mismatch")
    selection = summary["threshold_selection"]["random_forest"]
    return dict(
        artifact_version="1.0.0", created_at=datetime.now(timezone.utc).isoformat(),
        model=model, preprocessing=preprocessing,
        raw_feature_order=tuple(raw_feature_names), transformed_feature_order=tuple(transformed_feature_names),
        feature_definitions=feature_definitions(raw_feature_names), configuration=config.model_dump(mode="json"),
        selected_forest=summary["selected_forest"], forest_parameters=model.get_params(deep=False),
        decision_policy=dict(selected_threshold=selection["selected_threshold"],
                             reference_threshold=config.decision_threshold, selection_method=selection["method"],
                             selection_status=selection["status"], warning_policy_status=summary["warning_policy_status"]),
        research_metadata=dict(
            model_status="random_forest_experimental_not_live_validated", research_only=True,
            live_warning_allowed=False, data_kind=summary["data_kind"],
            experiment_version=summary["experiment_version"], test_period_status=summary["test_period_status"],
            historical_availability="unknown", recording_completeness="unknown", publication_version="unknown",
            target_definition="Arithmetic per-cow mean t-7..t-1 versus t+1..t+7; origin t separately eligible.",
            limitations=list(summary["limitations"]),
        ),
        software_versions={**summary["software_versions"], "python": platform.python_version()},
    )


def validate_artifact_destination(destination):
    path = Path(destination).expanduser().resolve()
    repository = Path(__file__).resolve().parents[3]
    if path.is_relative_to(repository):
        raise ValueError("model_artifact_must_be_outside_repository")
    if path.suffix.lower() != ".pkl" or not path.parent.is_dir():
        raise ValueError("existing_private_directory_and_pkl_extension_required")
    if path.exists():
        raise FileExistsError("artifact_destination_already_exists")
    return path


def save_model_artifact(bundle, destination):
    """No overwrite and no directory creation. Only trusted local pickle artifacts.

    Pickle is executable on loading; never load an untrusted artifact. Learned
    model parameters are sensitive too: keep this file private, local and out of Git.
    """
    if set(bundle) != ARTIFACT_KEYS:
        raise ValueError("unexpected_artifact_fields")
    metadata = bundle["research_metadata"]
    if (metadata["model_status"] != "random_forest_experimental_not_live_validated"
            or metadata["research_only"] is not True or metadata["live_warning_allowed"] is not False):
        raise ValueError("research_only_artifact_required")
    path = validate_artifact_destination(destination)
    # Serialize before opening destination, avoiding partial files on serialization failure.
    serialized = pickle.dumps(bundle, protocol=pickle.HIGHEST_PROTOCOL)
    with path.open("xb") as handle:
        handle.write(serialized)
