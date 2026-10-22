"""Synthetic artifact/rows only. No real artifact, database, or fit calls here."""

from datetime import datetime, timedelta, timezone
import json
import pickle

import numpy as np
import pytest
from pydantic import ValidationError

from components.member4_crisis_forecasting.prediction.research_prediction import (
    load_trusted_artifact, validate_prediction_artifact, predict_research_history, ResearchPrediction,
)
from components.member4_crisis_forecasting.output.prediction_publication import (
    PREDICTION_OBJECT, INSERT_PREDICTION, publish_approved_predictions,
)
from components.member4_crisis_forecasting.tests.test_model_artifact import synthetic_experiment
from components.member4_crisis_forecasting.tests.test_retrospective_training import START
from components.member4_crisis_forecasting.tests.test_retrospective_training import aggregate

NOW = datetime(2021, 1, 1, tzinfo=timezone.utc)
DIGEST = "a" * 64


def predict(fixture, **changes):
    rows, _, _, bundle = fixture
    arguments = dict(start_date=START + timedelta(days=230), end_date=START + timedelta(days=230),
                     generated_at=NOW, data_kind="synthetic")
    arguments.update(changes)
    return predict_research_history(rows, bundle, DIGEST, **arguments)


def test_prediction_reuses_fitted_model_and_preprocessing_without_fit(synthetic_experiment, monkeypatch):
    from sklearn.ensemble import RandomForestClassifier
    from components.member4_crisis_forecasting.prediction.feature_preprocessing import TrainingFeaturePreprocessor
    def forbidden(*args, **kwargs): raise AssertionError("inference must never fit")
    monkeypatch.setattr(RandomForestClassifier, "fit", forbidden)
    monkeypatch.setattr(TrainingFeaturePreprocessor, "fit", forbidden)
    outputs, summary = predict(synthetic_experiment)
    assert len(outputs) == 1 and summary["predictions"] == 1
    assert outputs[0].experiment_partition == "test_exploratory"
    assert outputs[0].research_only and not outputs[0].live_warning_allowed
    assert outputs[0].historical_availability == outputs[0].recording_completeness == "unknown"
    assert "assessment_date" not in json.dumps(summary)


def test_future_observations_change_outcomes_not_probabilities(synthetic_experiment):
    rows, cfg, summary, bundle = synthetic_experiment
    origin = START + timedelta(days=230)
    original, _ = predict(synthetic_experiment)
    changed = [row.model_copy(update={"target_litres_per_cow": 999, "thi_mean": 999,
                                     "mastitis_episodes": 999, "n_blood_alarms": 999})
               if row.date > origin else row for row in rows]
    altered, _ = predict((changed, cfg, summary, bundle))
    assert original[0].predicted_decline_probability == altered[0].predicted_decline_probability


def test_missing_future_actuals_do_not_remove_eligible_score(synthetic_experiment):
    rows, cfg, summary, bundle = synthetic_experiment
    origin = START + timedelta(days=230)
    truncated = [row for row in rows if row.date <= origin]
    outputs, _ = predict((truncated, cfg, summary, bundle))
    assert len(outputs) == 1 and outputs[0].actual_outcome is None
    assert outputs[0].outcome_reason == "incomplete_calendar_window"


def test_no_saved_threshold_keeps_classification_missing(synthetic_experiment):
    rows, cfg, summary, bundle = synthetic_experiment
    altered = {**bundle, "decision_policy": {**bundle["decision_policy"], "selected_threshold": None}}
    outputs, _ = predict((rows, cfg, summary, altered))
    assert outputs[0].predicted_decline is None
    assert outputs[0].classification_status == "no_saved_threshold"


def test_original_purge_dates_are_not_relabelled_as_test(synthetic_experiment):
    cfg = synthetic_experiment[1]
    outputs, summary = predict(synthetic_experiment, start_date=cfg.train_end, end_date=cfg.train_end)
    assert outputs == ()
    assert summary["excluded"]["original_purge_boundary"] == 1


def test_later_dates_are_post_experiment_not_new_final_test(synthetic_experiment):
    rows, cfg, summary, bundle = synthetic_experiment
    extended = [*rows, *(aggregate(i) for i in range(300, 320))]
    origin = START + timedelta(days=310)
    outputs, _ = predict((extended, cfg, summary, bundle), start_date=origin, end_date=origin)
    assert len(outputs) == 1
    assert outputs[0].experiment_partition == "post_experiment_research"


def test_source_switch_or_gap_withholds_predictions(synthetic_experiment):
    rows, cfg, summary, bundle = synthetic_experiment
    origin = START + timedelta(days=230)
    for altered_rows in ([row for row in rows if row.date != origin - timedelta(days=1)],
                         [row.model_copy(update={"target_source": "delpro"}) if row.date == origin else row for row in rows]):
        assert predict((altered_rows, cfg, summary, bundle))[0] == ()


def test_feature_order_corruption_is_rejected(synthetic_experiment):
    bundle = synthetic_experiment[3]
    with pytest.raises(ValueError, match="feature_definition_or_order"):
        validate_prediction_artifact({**bundle, "raw_feature_order": tuple(reversed(bundle["raw_feature_order"]))})


def test_trusted_load_requires_acknowledgement_before_reading(tmp_path):
    with pytest.raises(PermissionError):
        load_trusted_artifact(tmp_path / "nonexistent.pkl")


def test_only_new_trusted_synthetic_pickle_is_loaded(tmp_path, synthetic_experiment):
    path = tmp_path / "fictional.pkl"
    path.write_bytes(pickle.dumps(synthetic_experiment[3]))
    restored, digest = load_trusted_artifact(path, trust_local_artifact=True)
    assert len(digest) == 64
    assert restored["raw_feature_order"] == synthetic_experiment[3]["raw_feature_order"]


def test_prediction_roundtrip_and_missing_threshold_invariant(synthetic_experiment):
    output = predict(synthetic_experiment)[0][0]
    assert ResearchPrediction.model_validate_json(output.model_dump_json()) == output
    altered = {**output.model_dump(), "saved_threshold": None, "predicted_decline": True}
    with pytest.raises(ValidationError):
        ResearchPrediction.model_validate(altered)


def test_publication_gate_cannot_target_existing_assessment_table(synthetic_experiment):
    def forbidden(**kwargs): raise AssertionError("must not connect")
    with pytest.raises(PermissionError):
        publish_approved_predictions(predict(synthetic_experiment)[0],
            approved_object="c4_output.farm_risk_assessment_v1", host="synthetic", port=1, password="fictional", connect=forbidden)


def test_parameterized_prediction_only_mocked_publication(synthetic_experiment):
    calls = []
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, values): calls.append((sql, values))
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def cursor(self): return Cursor()
    assert publish_approved_predictions(predict(synthetic_experiment)[0], approved_object=PREDICTION_OBJECT,
            host="synthetic", port=1, password="fictional", connect=lambda **kwargs: Connection()) == 1
    assert len(calls) == 1 and calls[0][0] == INSERT_PREDICTION
    assert "farm_risk_assessment_v1" not in calls[0][0]


def test_cli_default_never_publishes_and_sanitizes_credentials(monkeypatch, capsys, synthetic_experiment):
    from components.member4_crisis_forecasting.prediction import predict_local
    from components.member4_crisis_forecasting.data_access import local_training_loader
    from components.member4_crisis_forecasting.output import prediction_publication
    rows, _, _, artifact = synthetic_experiment
    published = {**artifact, "research_metadata": {**artifact["research_metadata"], "data_kind": "published"}}
    monkeypatch.setattr(predict_local, "load_trusted_artifact", lambda *args, **kwargs: (published, DIGEST))
    monkeypatch.setattr(predict_local.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(predict_local, "getpass", lambda _: "FICTIONAL_PASSWORD")
    monkeypatch.setattr(local_training_loader, "load_approved_days", lambda **kwargs: rows)
    def forbidden(*args, **kwargs): raise AssertionError("default mode must not publish")
    monkeypatch.setattr(prediction_publication, "publish_approved_predictions", forbidden)
    origin = (START + timedelta(days=230)).isoformat()
    assert predict_local.main(["--artifact-path", "fictional.pkl", "--trust-local-artifact",
                               "--start-date", origin, "--end-date", origin]) == 0
    output = capsys.readouterr()
    assert "FICTIONAL_PASSWORD" not in output.out + output.err
    assert json.loads(output.out)["publication"] == "not_requested_no_writes"
