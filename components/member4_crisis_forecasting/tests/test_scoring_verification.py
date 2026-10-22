"""Fictional inputs and mocked loader only; no real database connections."""

from datetime import timedelta
import json

import pytest
from pydantic import ValidationError

from components.member4_crisis_forecasting.data_access.aggregate_mapper import validate_aggregate
from components.member4_crisis_forecasting.schemas.scoring_verification import (
    VerificationConfig, VerificationDate, VerificationMetadata,
)
from components.member4_crisis_forecasting.schemas.historical_dataset import AggregateMetadata
from components.member4_crisis_forecasting.services.scoring_verification import verify_scoring
from components.member4_crisis_forecasting.services import verify_scoring_local
from components.member4_crisis_forecasting.tests.test_scoring_output import configuration, DAY, CUTOFF, rule


def row(**changes):
    values = dict(date=DAY, target_source="shipment", target_litres_per_cow=20.0,
                  is_scoreable=True, milking=10.0, thi_mean=74.0, thi_max=None, hours_thi_above=None,
                  mastitis_episodes=2, udder_teat_episodes=1, other_health_episodes=None,
                  n_sessions=10, n_blood_alarms=1, n_conductivity_alarms=None)
    values.update(changes)
    return validate_aggregate(values)


def entry(**changes):
    timing = dict(observation_end=CUTOFF, available_at=CUTOFF, quality="ok")
    values = dict(observation_date=DAY, source="synthetic", source_version="synthetic-core",
                  climate=timing, biological=timing, operational=timing,
                  health_recording=dict(mastitis_episodes="complete", udder_teat_episodes="complete"),
                  operational_recording=dict(n_sessions="complete", n_blood_alarms="complete"))
    values.update(changes)
    return VerificationDate(metadata=AggregateMetadata(**values), assessment_cutoff=CUTOFF,
                            availability_evidence="verified")


def config(**changes):
    values = dict(version="synthetic-verification-v1", scoring=configuration(),
                  climate=dict(heat_stress_threshold=72))
    values.update(changes)
    return VerificationConfig(**values)


def metadata(days=None):
    return VerificationMetadata(version="synthetic-metadata-v1", quality_policy_version="synthetic-quality-v1",
                                days=(entry(),) if days is None else days)


def verify(rows=None, entries=None, cfg=None):
    return verify_scoring([row()] if rows is None else rows, cfg or config(), metadata(entries),
                          start_date=DAY, end_date=DAY, data_kind="synthetic", generated_at=CUTOFF)


def test_complete_genuinely_eligible_configured_inputs_are_scored():
    result = verify()
    assert result["score_available_days"] == dict(climate=1, biological=1, operational=1, combined=1)
    assert result["score_summaries"]["combined"] == dict(n=1, mean=42.5, min=42.5, max=42.5)
    assert result["category_counts"] == {"medium_provisional": 1}
    assert result["research_only"] and not result["live_warning_allowed"]
    assert "output_id" not in json.dumps(result)
    assert "assessment_date" not in json.dumps(result)


def test_missing_metadata_reports_raw_presence_without_any_scores():
    result = verify(entries=())
    assert result["raw_indicator_counts"]["thi_mean"]["observed"] == 1
    assert result["score_summaries"]["combined"]["mean"] is None
    assert result["unavailable_reason_counts"]["missing_per_date_metadata"] == 1


def test_unknown_availability_is_not_invented_from_existing_timestamps():
    unknown = entry().model_copy(update={"availability_evidence": "unknown"})
    result = verify(entries=(unknown,))
    assert result["score_available_days"]["combined"] == 0
    assert result["unavailable_reason_counts"]["historical_availability_evidence_unknown"] == 1


@pytest.mark.parametrize("changes", [
    {"source_version": None}, {"climate": {}},
    {"health_recording": {}}, {"operational_recording": {}},
])
def test_missing_provenance_timing_or_recording_quality_withholds_combined(changes):
    result = verify(entries=(entry(**changes),))
    assert result["score_available_days"]["combined"] == 0
    assert result["category_counts"] == {"unavailable": 1}


def test_raw_zero_is_observed_and_is_not_missing():
    result = verify(rows=[row(mastitis_episodes=0, udder_teat_episodes=None)])
    assert result["raw_indicator_counts"]["mastitis_episodes"] == dict(observed=1, missing=0, recorded_zero=1)
    assert result["raw_indicator_counts"]["udder_teat_episodes"]["missing"] == 1
    assert result["score_available_days"]["biological"] == 0


def test_eligibility_is_not_inferred_from_production_scoreability():
    result = verify(rows=[row(is_scoreable=False)])
    assert result["score_available_days"]["combined"] == 1


def test_future_domain_availability_withholds_only_that_domain():
    late = entry(climate=dict(observation_end=CUTOFF, available_at=CUTOFF + timedelta(hours=1), quality="ok"))
    result = verify(entries=(late,))
    assert result["score_available_days"]["climate"] == 0
    assert result["score_available_days"]["biological"] == 1
    assert result["unavailable_reason_counts"]["climate:unavailable_at_cutoff"] == 1


def test_unknown_threshold_and_missing_historical_baseline_are_not_created():
    cfg = config(climate={}, scoring=configuration(climate_rules=(rule("absolute_exceedance"), rule("historical_exceedance"))))
    result = verify(cfg=cfg)
    assert result["score_available_days"]["climate"] == 0
    assert result["score_available_days"]["combined"] == 0


def test_empty_range_and_calendar_gaps_are_safe():
    result = verify(rows=[], entries=())
    assert result["missing_calendar_days"] == 1
    assert result["score_summaries"]["combined"]["n"] == 0


def test_duplicate_metadata_and_unknown_quality_policy_are_rejected():
    with pytest.raises(ValidationError):
        metadata((entry(), entry()))
    with pytest.raises(ValidationError):
        VerificationMetadata(version="synthetic-v1", quality_policy_version=" ", days=())


def test_explicit_documents_roundtrip_and_non_json_rejected(tmp_path):
    config_path, metadata_path = tmp_path / "synthetic-config.json", tmp_path / "synthetic-metadata.json"
    config_path.write_text(config().model_dump_json(), encoding="utf-8")
    metadata_path.write_text(metadata().model_dump_json(), encoding="utf-8")
    parsed_config, parsed_metadata = verify_scoring_local.read_documents(config_path, metadata_path)
    assert parsed_config == config() and parsed_metadata == metadata()
    with pytest.raises(ValueError, match="explicit_json"):
        verify_scoring_local.read_documents(tmp_path / ".env", metadata_path)


def test_cli_uses_mocked_read_only_loader_and_aggregate_summary(monkeypatch, capsys):
    from components.member4_crisis_forecasting.data_access import local_training_loader
    calls = []
    monkeypatch.setattr(verify_scoring_local, "read_documents", lambda *args: (config(), metadata()))
    monkeypatch.setattr(verify_scoring_local.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(verify_scoring_local, "getpass", lambda _: "FICTIONAL_PASSWORD")
    monkeypatch.delenv("C4_DB_PORT", raising=False)
    def fake_loader(**kwargs):
        calls.append((kwargs["port"], kwargs["test_end"]))
        return (row(),)
    monkeypatch.setattr(local_training_loader, "load_approved_days", fake_loader)
    # Published CLI refuses synthetic provenance; no scores are fabricated.
    assert verify_scoring_local.main(["--config", "synthetic-config.json", "--metadata", "synthetic-metadata.json",
                                     "--start-date", DAY.isoformat(), "--end-date", DAY.isoformat()]) == 0
    output = capsys.readouterr()
    assert "FICTIONAL_PASSWORD" not in output.out + output.err
    result = json.loads(output.out)
    assert result["unavailable_reason_counts"]["metadata_source_mismatch"] == 1
    assert calls == [(5432, DAY)]


def test_invalid_config_is_sanitized_before_password_or_loader(monkeypatch, capsys):
    def fail(*args): raise ValueError("PRIVATE_INPUT_DO_NOT_EXPOSE")
    def forbidden(*args): raise AssertionError("must not request credentials")
    monkeypatch.setattr(verify_scoring_local, "read_documents", fail)
    monkeypatch.setattr(verify_scoring_local, "getpass", forbidden)
    assert verify_scoring_local.main(["--config", "synthetic-config.json", "--metadata", "synthetic-metadata.json",
                                     "--start-date", DAY.isoformat(), "--end-date", DAY.isoformat()]) == 2
    output = capsys.readouterr()
    assert "PRIVATE_INPUT_DO_NOT_EXPOSE" not in output.out + output.err
    assert json.loads(output.out)["status"] == "scoring_verification_failed"
