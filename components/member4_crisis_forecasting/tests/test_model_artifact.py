"""Synthetic model artifacts only, private pytest temporary files, no DB calls."""

from datetime import timedelta
import pickle

import numpy as np
import pytest

from components.member4_crisis_forecasting.prediction.chronological_training import run_experiment
from components.member4_crisis_forecasting.prediction.integrated_features import integrated_features
from components.member4_crisis_forecasting.prediction.historical_features import production_features
from components.member4_crisis_forecasting.prediction.model_artifact import (
    ARTIFACT_KEYS, save_model_artifact, validate_artifact_destination,
)
from components.member4_crisis_forecasting.tests.test_retrospective_training import aggregate, config, START


@pytest.fixture(scope="module")
def synthetic_experiment():
    rows = [aggregate(i) for i in range(300)]
    cfg = config(forest_comparison="validation_small", threshold_selection="validation_f1")
    captured = []
    summary = run_experiment(rows, cfg, data_kind="synthetic", artifact_callback=captured.append)
    return rows, cfg, summary, captured[0]


def test_selected_model_configuration_and_private_allowlist(synthetic_experiment):
    _, cfg, summary, artifact = synthetic_experiment
    assert set(artifact) == ARTIFACT_KEYS
    assert artifact["selected_forest"] == summary["selected_forest"]
    selected = summary["forest_validation_comparison"][summary["selected_forest"]]["settings"]
    assert all(artifact["model"].get_params()[key] == value for key, value in selected.items())
    assert artifact["configuration"] == cfg.model_dump(mode="json")
    assert list(artifact["raw_feature_order"]) == summary["features"]
    assert list(artifact["transformed_feature_order"]) == summary["preprocessing"]["output_feature_names"]
    assert artifact["decision_policy"]["selected_threshold"] == summary["threshold_selection"]["random_forest"]["selected_threshold"]
    flags = artifact["research_metadata"]
    assert flags["model_status"] == "random_forest_experimental_not_live_validated"
    assert flags["research_only"] and not flags["live_warning_allowed"]
    assert flags["data_kind"] == "synthetic"
    assert not {"rows", "x_train", "y_train", "password", "credentials", "predictions"} & set(artifact)


def test_serialized_model_and_preprocessing_reproduce_probabilities(tmp_path, synthetic_experiment):
    rows, _, _, artifact = synthetic_experiment
    destination = tmp_path / "fictional-research-model.pkl"
    save_model_artifact(artifact, destination)
    # Only this trusted, newly generated synthetic pickle is loaded in the test.
    with destination.open("rb") as handle:
        restored = pickle.load(handle)
    raw = [integrated_features({row.date: row for row in rows}, START + timedelta(days=40), "shipment")]
    expected = artifact["model"].predict_proba(artifact["preprocessing"].transform(raw))
    actual = restored["model"].predict_proba(restored["preprocessing"].transform(raw))
    np.testing.assert_array_equal(actual, expected)
    assert restored["feature_definitions"] == artifact["feature_definitions"]
    with pytest.raises(FileExistsError):
        save_model_artifact(artifact, destination)


def test_opt_in_callback_does_not_change_evaluation_summary(synthetic_experiment):
    rows, cfg, expected, _ = synthetic_experiment
    assert run_experiment(rows, cfg, data_kind="synthetic") == expected


def test_production_only_mode_stores_explicit_identity_preprocessing():
    captured = []
    rows = [aggregate(i) for i in range(300)]
    run_experiment(rows, config(feature_set="production_only"), data_kind="synthetic", artifact_callback=captured.append)
    artifact = captured[0]
    assert artifact["preprocessing"] is None
    assert artifact["raw_feature_order"] == artifact["transformed_feature_order"]
    features = production_features({row.date: row for row in rows}, START + timedelta(days=40), "shipment")
    assert artifact["model"].predict_proba([features]).shape == (1, 2)


def test_insufficient_data_never_calls_save_hook():
    captured = []
    result = run_experiment([], config(), data_kind="synthetic", artifact_callback=captured.append)
    assert result["status"] == "insufficient_data"
    assert captured == []


def test_invalid_artifact_flags_or_extra_data_are_not_saved(tmp_path, synthetic_experiment):
    artifact = synthetic_experiment[3]
    with pytest.raises(ValueError, match="unexpected_artifact_fields"):
        save_model_artifact({**artifact, "rows": []}, tmp_path / "rejected.pkl")
    changed = {**artifact, "research_metadata": {**artifact["research_metadata"], "live_warning_allowed": True}}
    with pytest.raises(ValueError, match="research_only"):
        save_model_artifact(changed, tmp_path / "rejected.pkl")
    assert not (tmp_path / "rejected.pkl").exists()


def test_private_new_destination_is_required(tmp_path):
    from pathlib import Path
    component_directory = Path(__file__).resolve().parents[1]
    with pytest.raises(ValueError, match="outside_repository"):
        validate_artifact_destination(component_directory / "not-allowed.pkl")
    with pytest.raises(ValueError, match="pkl_extension"):
        validate_artifact_destination(tmp_path / "not-allowed.json")


def test_cli_optional_artifact_uses_existing_loader_with_mocks(monkeypatch, capsys, tmp_path):
    from components.member4_crisis_forecasting.prediction import train_local
    from components.member4_crisis_forecasting.prediction import model_artifact
    from components.member4_crisis_forecasting.data_access import local_training_loader
    monkeypatch.setattr(train_local.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(train_local, "getpass", lambda _: "FICTIONAL_PASSWORD")
    monkeypatch.setattr(local_training_loader, "load_approved_days", lambda **kwargs: ())
    saved = []
    monkeypatch.setattr(model_artifact, "save_model_artifact", lambda bundle, path: saved.append((bundle, path)))
    def experiment(rows, cfg, *, data_kind, artifact_callback):
        assert rows == () and data_kind == "published"
        artifact_callback({"synthetic_test_stub": True})
        return {"status": "evaluated_retrospectively"}
    monkeypatch.setattr(train_local, "run_experiment", experiment)
    destination = tmp_path / "synthetic-cli-model.pkl"
    assert train_local.main([
        "--acknowledge-retrospective-limitations", "--milk-source", "shipment",
        "--decline-threshold-pct", "10", "--decision-threshold", "0.5",
        "--train-end", "2020-04-01", "--validation-end", "2020-06-01", "--test-end", "2020-08-01",
        "--artifact-path", str(destination),
    ]) == 0
    assert len(saved) == 1 and saved[0][1] == destination
    output = capsys.readouterr()
    assert "FICTIONAL_PASSWORD" not in output.out + output.err
    assert "saved_private_research_artifact" in output.out
