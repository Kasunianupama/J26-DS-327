"""Synthetic research rows; all database-capable paths are mocked or denied."""

from datetime import date, datetime, timezone
import json

import pytest
from pydantic import ValidationError

from components.member4_crisis_forecasting.data_access.aggregate_mapper import validate_aggregate
from components.member4_crisis_forecasting.schemas.risk_output import DescriptiveRiskOutput, validate_research_output
from components.member4_crisis_forecasting.services.retrospective_scoring import RetrospectiveResearchConfig, calculate_research_outputs
from components.member4_crisis_forecasting.output.publisher import APPROVAL_OBJECT, prepare_publication
from components.member4_crisis_forecasting.output.local_publication import publish_approved_batch, INSERT_RESEARCH
from components.member4_crisis_forecasting.tests.test_scoring_output import configuration, rule

START, END = date(2025, 1, 1), date(2026, 12, 31)
GENERATED = datetime(2026, 12, 31, 23, tzinfo=timezone.utc)


def research_config(**changes):
    values = dict(version="synthetic-descriptive-v1", assumptions="Fictional research assumptions; recording quality is unknown.",
                  scoring=configuration(), climate=dict(heat_stress_threshold=72))
    values.update(changes)
    return RetrospectiveResearchConfig(**values)


def synthetic_row(**changes):
    values = dict(date=START, target_source=None, target_litres_per_cow=None, is_scoreable=False,
                  milking=None, thi_mean=74, thi_max=None, hours_thi_above=None,
                  mastitis_episodes=2, udder_teat_episodes=1, other_health_episodes=None,
                  n_sessions=10, n_blood_alarms=1, n_conductivity_alarms=None)
    values.update(changes)
    return validate_aggregate(values)


def calculate(rows=None, cfg=None):
    return calculate_research_outputs([synthetic_row()] if rows is None else rows, cfg or research_config(),
        start_date=START, end_date=END, generated_at=GENERATED, data_kind="synthetic")


def test_descriptive_scores_are_not_fabricated_verified_metadata():
    outputs, summary = calculate()
    output = outputs[0]
    assert output.combined_score == 42.5
    assert output.assessment_cutoff is None
    assert output.provenance.availability == "unknown"
    assert output.provenance.core_version is None
    assert output.recording_quality == "unknown"
    assert output.contract_version == "1.1.0"
    assert not output.live_warning_allowed
    assert summary["score_basis"] == "descriptive_retrospective_unverified"
    assert "assessment_date" not in json.dumps(summary)


@pytest.mark.parametrize("changes", [{"thi_mean": None}, {"mastitis_episodes": None}, {"n_blood_alarms": None}])
def test_missing_required_measurement_is_unavailable_not_zero(changes):
    outputs, summary = calculate([synthetic_row(**changes)])
    assert outputs[0].combined_score is None
    assert outputs[0].risk_category == "unavailable"
    assert summary["score_summaries"]["combined"]["mean"] is None


def test_unverified_ratios_and_historical_anomalies_stay_unavailable():
    cfg = research_config(scoring=configuration(
        climate_rules=(rule("historical_exceedance"),), operational_rules=(rule("blood_alarms_per_session"),)))
    outputs, _ = calculate(cfg=cfg)
    assert outputs[0].domains[0].score is None
    assert outputs[0].domains[2].score is None


def test_recorded_zero_is_preserved_as_descriptive_not_clinical_absence():
    outputs, _ = calculate([synthetic_row(thi_mean=72, mastitis_episodes=0, udder_teat_episodes=0, n_blood_alarms=0)])
    assert outputs[0].combined_score == 0
    assert outputs[0].recording_quality == "unknown"


def test_contract_roundtrip_and_publication_have_nullable_historical_cutoff():
    output = calculate()[0][0]
    assert validate_research_output(json.loads(output.model_dump_json())) == output
    record = prepare_publication(output)
    assert record["assessment_cutoff"] is None
    assert record["score_basis"] == "descriptive_retrospective_unverified"
    with pytest.raises(ValidationError):
        DescriptiveRiskOutput.model_validate({**output.model_dump(), "assessment_cutoff": GENERATED})


def test_publication_denied_before_any_connection_without_approval():
    def forbidden(**kwargs): raise AssertionError("must not connect")
    with pytest.raises(PermissionError):
        publish_approved_batch(calculate()[0], host="synthetic", port=1, password="fictional", connect=forbidden)


def test_approved_publication_is_parameterized_fixed_table_with_mock_connection():
    calls = []
    class FakeCursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params): calls.append((sql, params))
    class FakeConnection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def cursor(self): return FakeCursor()
    def connect(**kwargs):
        assert kwargs["user"] == "farmx_c4" and kwargs["dbname"] == "farmx_app"
        return FakeConnection()
    count = publish_approved_batch(calculate()[0], approved_object=APPROVAL_OBJECT,
                                  host="synthetic", port=1, password="fictional", connect=connect)
    assert count == len(calls) == 1
    assert calls[0][0] == INSERT_RESEARCH
    assert INSERT_RESEARCH.startswith("INSERT INTO c4_output.farm_risk_assessment_v1 (")
    assert calls[0][1][4] is None


def test_cli_calculation_cannot_publish_by_default(monkeypatch, capsys):
    from components.member4_crisis_forecasting.services import research_outputs_local as cli
    from components.member4_crisis_forecasting.data_access import local_training_loader
    from components.member4_crisis_forecasting.output import local_publication
    monkeypatch.setattr(cli, "read_research_config", lambda _: research_config())
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli, "getpass", lambda _: "FICTIONAL_SECRET")
    monkeypatch.setattr(local_training_loader, "load_approved_days", lambda **kwargs: [synthetic_row()])
    def forbidden(*args, **kwargs): raise AssertionError("publication forbidden")
    monkeypatch.setattr(local_publication, "publish_approved_batch", forbidden)
    assert cli.main(["--config", "synthetic.json"]) == 0
    output = capsys.readouterr()
    assert "FICTIONAL_SECRET" not in output.out + output.err
    assert json.loads(output.out)["publication"] == "not_requested_no_writes"


def test_partial_publication_flags_fail_before_credentials(monkeypatch, capsys):
    from components.member4_crisis_forecasting.services import research_outputs_local as cli
    def forbidden(*args): raise AssertionError("must not read config or credentials")
    monkeypatch.setattr(cli, "read_research_config", forbidden)
    monkeypatch.setattr(cli, "getpass", forbidden)
    assert cli.main(["--config", "synthetic.json", "--publish-approved"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "research_workflow_failed"
