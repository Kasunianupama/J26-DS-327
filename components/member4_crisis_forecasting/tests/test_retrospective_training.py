"""Synthetic unit tests only; every loader call injects a fake connection."""

from datetime import date, datetime, timedelta, timezone
import importlib
import json

import pytest
from pydantic import ValidationError

from components.member4_crisis_forecasting.data_access.aggregate_mapper import APPROVED_COLUMNS, validate_aggregate
from components.member4_crisis_forecasting.data_access.local_training_loader import load_approved_days, SELECT_APPROVED_DAYS
from components.member4_crisis_forecasting.prediction.chronological_training import (
    ExperimentConfig, classification_metrics, run_experiment, split_name,
)
from components.member4_crisis_forecasting.prediction.decline_target import (
    DeclineTargetConfig, HistoricalLabelRequest, generate_decline_labels,
)
from components.member4_crisis_forecasting.prediction.historical_features import production_features
from components.member4_crisis_forecasting.prediction.retrospective import retrospective_targets
from components.member4_crisis_forecasting.schemas.production_inputs import ProductionDay

START = date(2020, 1, 1)


def aggregate(index, **changes):
    values = dict(
        date=START + timedelta(days=index), target_source="shipment",
        target_litres_per_cow=16.0 if index % 30 >= 20 else 20.0,
        is_scoreable=True, milking=10.0, thi_mean=None, thi_max=None, hours_thi_above=None,
        mastitis_episodes=None, udder_teat_episodes=None, other_health_episodes=None,
        n_sessions=None, n_blood_alarms=None, n_conductivity_alarms=None,
    )
    values.update(changes)
    return validate_aggregate(values)


def config(**changes):
    values = dict(milk_source="shipment", decline_threshold_pct=10,
                  decision_threshold=0.5, train_end=START + timedelta(days=119),
                  validation_end=START + timedelta(days=209), test_end=START + timedelta(days=299))
    values.update(changes)
    return ExperimentConfig(**values)


def test_purge_uses_calendar_outcome_end():
    cfg = config()
    assert split_name(cfg.train_end - timedelta(days=7), cfg.train_end, cfg) == "train"
    assert split_name(cfg.train_end - timedelta(days=6), cfg.train_end + timedelta(days=1), cfg) is None
    assert split_name(cfg.train_end + timedelta(days=1), cfg.train_end + timedelta(days=8), cfg) == "validation"
    assert split_name(cfg.validation_end, cfg.validation_end + timedelta(days=7), cfg) is None
    assert split_name(cfg.validation_end + timedelta(days=1), cfg.validation_end + timedelta(days=8), cfg) == "test"
    assert split_name(cfg.test_end, cfg.test_end + timedelta(days=7), cfg) is None


def test_features_ignore_origin_future_flags_and_nonproduction_domains():
    rows = [aggregate(i) for i in range(30)]
    origin = START + timedelta(days=10)
    by_date = {row.date: row for row in rows}
    expected = production_features(by_date, origin, "shipment")
    altered = {row.date: aggregate(i, is_scoreable=False, thi_mean=999,
                                  n_blood_alarms=999, target_litres_per_cow=999 if i >= 10 else row.target_litres_per_cow)
               for i, row in enumerate(rows)}
    assert expected == production_features(altered, origin, "shipment")


@pytest.mark.parametrize("problem", ["gap", "source", "missing"])
def test_missing_or_incompatible_feature_history_is_not_imputed(problem):
    rows = [aggregate(i) for i in range(15)]
    if problem == "gap":
        rows.pop(1)
    else:
        rows[1] = aggregate(1, **({"target_source": "delpro"} if problem == "source" else {"target_litres_per_cow": None}))
    assert production_features({row.date: row for row in rows}, START + timedelta(days=7), "shipment") is None


def test_retrospective_and_existing_generator_agree_on_synthetic_complete_windows():
    rows = [aggregate(i, target_litres_per_cow=20.0 if i <= 7 else 18.0) for i in range(15)]
    timing = lambda d: datetime.combine(d, datetime.max.time(), tzinfo=timezone.utc)
    production = [ProductionDay(
        observation_date=row.date, observation_end=timing(row.date), available_at=timing(row.date),
        source="synthetic", source_version="fictional", quality="ok", milk_source=row.target_source,
        target_litres_per_cow=row.target_litres_per_cow, is_scoreable=row.is_scoreable,
    ) for row in rows]
    cfg = DeclineTargetConfig(decline_threshold_pct=10)
    original = generate_decline_labels(HistoricalLabelRequest(
        days=production, prediction_cutoffs=[timing(rows[7].date)], labels_as_of=timing(rows[-1].date), config=cfg,
    ))[0]
    retrospective = next(target for target in retrospective_targets(rows, "shipment", cfg)
                         if target.origin == rows[7].date)
    assert retrospective.label is original.label is True
    assert retrospective.outcome_end == original.outcome_end


@pytest.mark.parametrize("changes,reason", [
    ({"is_scoreable": False}, "etl_ineligible_window"),
    ({"target_source": "delpro"}, "mixed_or_missing_milk_source"),
    ({"target_litres_per_cow": None}, "missing_production"),
])
def test_origin_eligibility_and_source_consistency_remain_required(changes, reason):
    rows = [aggregate(i) for i in range(21)]
    rows[7] = aggregate(7, **changes)
    targets = retrospective_targets(rows, "shipment", DeclineTargetConfig(decline_threshold_pct=10))
    if changes.get("target_source") == "delpro":
        # The origin belongs to the other source; neighboring windows still reject mixing.
        assert all(target.origin != rows[7].date for target in targets)
        neighbor = next(target for target in targets if target.origin == rows[8].date)
        assert neighbor.label is None and neighbor.reason == reason
    else:
        target = next(item for item in targets if item.origin == rows[7].date)
        assert target.label is None and target.reason == reason


def test_full_synthetic_training_returns_aggregate_metrics_and_is_deterministic():
    rows = [aggregate(i) for i in range(300)]
    summary = run_experiment(rows, config(), data_kind="synthetic")
    assert summary == run_experiment(list(reversed(rows)), config(), data_kind="synthetic")
    assert summary["status"] == "evaluated_retrospectively"
    assert summary["data_kind"] == "synthetic"
    assert summary["historical_availability"] == "unknown"
    assert set(summary["models"]) == {"random_forest", "training_prior_baseline"}
    for model in summary["models"].values():
        assert set(model) == {"validation", "test"}
        for metrics in model.values():
            assert metrics["n"] == sum(sum(row) for row in metrics["confusion_matrix"])
            assert metrics["pr_auc_average_precision"] is not None
    assert "per_row_predictions" not in json.dumps(summary, allow_nan=False)


@pytest.mark.parametrize("weight", [None, "balanced_subsample"])
def test_random_forest_fits_only_training_samples_with_reproducible_settings(monkeypatch, weight):
    import components.member4_crisis_forecasting.prediction.chronological_training as training
    original = training.RandomForestClassifier.fit
    observed = []
    def spy(self, x, y, **kwargs):
        observed.append(len(x))
        assert self.random_state == 0
        assert self.n_jobs == 1
        assert self.n_estimators == 200
        assert self.max_depth == 5
        assert self.min_samples_leaf == 5
        assert self.class_weight == weight
        return original(self, x, y, **kwargs)
    monkeypatch.setattr(training.RandomForestClassifier, "fit", spy)
    result = run_experiment([aggregate(i) for i in range(300)], config(class_weight=weight), data_kind="synthetic")
    assert observed == [result["splits"]["train"]["n"]]


def test_original_unweighted_fixed_threshold_mode_remains_available():
    cfg = config(feature_set="production_only")
    assert cfg.class_weight is None and cfg.threshold_selection == "fixed"
    result = run_experiment([aggregate(i) for i in range(300)], cfg, data_kind="synthetic")
    assert result["models"] == result["reference_models"]
    assert all(item["selected_threshold"] == 0.5 for item in result["threshold_selection"].values())
    assert result["test_period_status"] == "exploratory_not_untouched_final"


def test_validation_selection_is_unchanged_when_only_test_actuals_change():
    rows = [aggregate(i) for i in range(300)]
    cfg = config(class_weight="balanced_subsample", threshold_selection="validation_f1")
    first = run_experiment(rows, cfg, data_kind="synthetic")
    changed = [aggregate(i, target_litres_per_cow=30.0) if row.date > cfg.validation_end else row
               for i, row in enumerate(rows)]
    second = run_experiment(changed, cfg, data_kind="synthetic")
    assert first["threshold_selection"] == second["threshold_selection"]
    for name in first["models"]:
        assert first["models"][name]["validation"] == second["models"][name]["validation"]


def test_constant_target_empty_source_and_insufficient_data_are_safe():
    for rows, cfg in [([], config()),
                      ([aggregate(i, target_litres_per_cow=20) for i in range(300)], config()),
                      ([aggregate(i) for i in range(300)], config(milk_source="delpro")),
                      ([aggregate(i) for i in range(30)], config())]:
        result = run_experiment(rows, cfg, data_kind="synthetic")
        assert result["status"] == "insufficient_data"
        assert result["models"] == {}


def test_undefined_metrics_are_explicit_nulls():
    result = classification_metrics([0, 0], [0.1, 0.2], 0.5)
    assert result["precision"] is result["recall"] is result["f1"] is None
    assert result["pr_auc_average_precision"] is None
    assert result["confusion_matrix"] == [[2, 0], [0, 0]]


def test_known_metrics():
    result = classification_metrics([0, 0, 1, 1], [0.1, 0.7, 0.4, 0.9], 0.5)
    assert result["precision"] == result["recall"] == result["f1"] == 0.5
    assert result["confusion_matrix"] == [[1, 1], [1, 1]]


@pytest.mark.parametrize("changes", [{"validation_end": START}, {"decision_threshold": 1},
                                    {"decline_threshold_pct": 0}, {"min_train_samples": 1}])
def test_invalid_experiment_config(changes):
    with pytest.raises(ValidationError):
        config(**changes)


def test_mocked_loader_selects_only_approved_columns_and_is_read_only():
    calls = []
    class FakeCursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params=None): calls.append((sql, params))
        def __iter__(self): return iter([aggregate(0).model_dump()])
    class FakeConnection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def cursor(self): return FakeCursor()
    def fake_connect(**kwargs):
        assert kwargs["dbname"] == "farmx_app" and kwargs["user"] == "farmx_c4"
        assert "read_only=on" in kwargs["options"]
        return FakeConnection()
    result = load_approved_days(host="synthetic", port=1, password="fictional", test_end=START, connect=fake_connect)
    assert len(result) == 1
    columns = SELECT_APPROVED_DAYS.split("SELECT")[1].split("FROM")[0]
    assert tuple(item.strip() for item in columns.split(",")) == APPROVED_COLUMNS
    assert len(calls) == 2 and "READ ONLY" in calls[0][0]
    assert calls[1][1] == (START,)


def test_cli_import_does_not_connect(monkeypatch):
    import psycopg
    def forbidden(*args, **kwargs): raise AssertionError("connection forbidden in unit test")
    monkeypatch.setattr(psycopg, "connect", forbidden)
    importlib.import_module("components.member4_crisis_forecasting.prediction.train_local")


def test_cli_sanitizes_failures_and_does_not_print_password(monkeypatch, capsys):
    from components.member4_crisis_forecasting.prediction import train_local
    from components.member4_crisis_forecasting.data_access import local_training_loader
    monkeypatch.setattr(train_local.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(train_local, "getpass", lambda _: "DO_NOT_EXPOSE")
    monkeypatch.delenv("C4_DB_PORT", raising=False)
    observed_ports = []
    def fail(**kwargs):
        observed_ports.append(kwargs["port"])
        raise RuntimeError("DO_NOT_EXPOSE")
    monkeypatch.setattr(local_training_loader, "load_approved_days", fail)
    assert train_local.main([
        "--acknowledge-retrospective-limitations", "--milk-source", "shipment",
        "--decline-threshold-pct", "10", "--decision-threshold", "0.5",
        "--train-end", "2020-04-01", "--validation-end", "2020-06-01", "--test-end", "2020-08-01",
    ]) == 2
    assert observed_ports == [5432]
    output = capsys.readouterr()
    assert "DO_NOT_EXPOSE" not in output.out + output.err
    assert json.loads(output.out)["status"] == "local_workflow_failed"
