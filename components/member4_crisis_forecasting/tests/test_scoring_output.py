"""Fictional scoring choices only; memory sinks, no DB or SQL execution."""

from datetime import date, datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from components.member4_crisis_forecasting.schemas.daily_inputs import DailyRiskInput
from components.member4_crisis_forecasting.schemas.biological_inputs import BiologicalInput, HealthRecordingQuality
from components.member4_crisis_forecasting.schemas.operational_inputs import OperationalInput, OperationalRecordingQuality
from components.member4_crisis_forecasting.schemas.risk_output import (
    FarmRiskOutput, IndicatorRule, Provenance, ScoringConfig,
)
from components.member4_crisis_forecasting.climate.environmental_risk import ClimateConfig
from components.member4_crisis_forecasting.services.scoring_service import assess_and_score
from components.member4_crisis_forecasting.output.publisher import (
    APPROVAL_OBJECT, prepare_publication, publish_to_approved_sink,
)

DAY = date(2020, 1, 1)
CUTOFF = datetime(2020, 1, 1, 23, 59, 59, tzinfo=timezone.utc)


def rule(feature, lower=0, upper=4, direction="higher_is_riskier"):
    return IndicatorRule(feature=feature, lower=lower, upper=upper, direction=direction,
                         rationale="Fictional synthetic test rule; not clinically validated.")


def configuration(**changes):
    values = dict(version="synthetic-v1", rationale="Fictional research configuration, not validated.",
                  climate_rules=(rule("absolute_exceedance"),),
                  biological_rules=(rule("mastitis_episodes"), rule("udder_teat_episodes")),
                  operational_rules=(rule("n_blood_alarms"),),
                  climate_weight=.4, biological_weight=.3, operational_weight=.3,
                  medium_starts_at=30, high_starts_at=70)
    values.update(changes)
    return ScoringConfig(**values)


def make_output(*, missing_climate=False, unknown_health=False, bio_missing=False,
                no_inputs=False, config=None, changes=None):
    values = dict(observation_date=DAY, observation_end=CUTOFF, available_at=CUTOFF,
                  source="synthetic", source_version="synthetic-core", quality="ok",
                  thi_mean=74, mastitis_episodes=2, udder_teat_episodes=1,
                  n_sessions=10, n_blood_alarms=1)
    values.update(changes or {})
    if bio_missing:
        values["udder_teat_episodes"] = None
    day = DailyRiskInput(**values)
    return assess_and_score(
        output_id=UUID("00000000-0000-0000-0000-000000000001"), assessment_date=DAY,
        assessment_cutoff=CUTOFF, generated_at=CUTOFF, config=config or configuration(),
        provenance=Provenance(source="synthetic", core_version="synthetic-core"),
        climate_input=None if no_inputs or missing_climate else day,
        climate_config=ClimateConfig(heat_stress_threshold=72),
        biological_input=None if no_inputs else BiologicalInput(day=day, recording_quality=HealthRecordingQuality(
            mastitis_episodes="unknown" if unknown_health else "complete", udder_teat_episodes="complete")),
        operational_input=None if no_inputs else OperationalInput(day=day, recording_quality=OperationalRecordingQuality(
            n_sessions="complete", n_blood_alarms="complete")),
    )


def test_scores_fixed_weighted_sum_and_separate_health_categories():
    output = make_output()
    assert [domain.score for domain in output.domains] == [50, 50, 25]
    assert output.combined_score == 42.5
    assert output.risk_category == "medium_provisional"
    assert output.contributions == {"climate": 20, "biological": 15, "operational": 7.5}
    assert output.domains[1].score == 50  # MAX, not summing mastitis and udder scores.
    assert output.data_completeness == "complete"


@pytest.mark.parametrize("kwargs", [{"missing_climate": True}, {"bio_missing": True}, {"unknown_health": True}])
def test_missing_information_withholds_combined_score_without_renormalizing(kwargs):
    output = make_output(**kwargs)
    assert output.combined_score is None
    assert output.risk_category == "unavailable"
    assert output.data_completeness == "partial"
    assert any(value is None for value in output.contributions.values())


def test_all_unavailable_is_not_low_risk():
    output = make_output(no_inputs=True)
    assert output.data_completeness == "unavailable"
    assert output.combined_score is None
    assert output.risk_category == "unavailable"


def test_recorded_zero_is_scored_and_high_scores_are_clipped():
    output = make_output(changes=dict(thi_mean=72, mastitis_episodes=0, udder_teat_episodes=0, n_blood_alarms=0))
    assert output.combined_score == 0
    assert output.risk_category == "low_provisional"
    assert make_output(changes={"thi_mean": 100}).domains[0].score == 100


def test_low_session_count_rule_direction_is_explicit():
    cfg = configuration(operational_rules=(rule("n_sessions", 0, 20, "lower_is_riskier"),))
    assert make_output(config=cfg).domains[2].score == 50


@pytest.mark.parametrize("medium,high,expected", [(42.5, 80, "medium_provisional"), (20, 42.5, "high_provisional")])
def test_category_boundaries_are_inclusive_and_provisional(medium, high, expected):
    output = make_output(config=configuration(medium_starts_at=medium, high_starts_at=high))
    assert output.risk_category == expected


def test_ratio_scoring_is_unavailable_without_verified_denominator_semantics():
    cfg = configuration(operational_rules=(rule("blood_alarms_per_session"),))
    assert make_output(config=cfg).domains[2].score is None


def test_operational_inconsistency_withholds_affected_score():
    assert make_output(changes={"n_sessions": 0}).domains[2].score is None


@pytest.mark.parametrize("changes", [
    {"climate_weight": .8}, {"medium_starts_at": 90, "high_starts_at": 80},
    {"biological_rules": ()}, {"climate_rules": (rule("mastitis_episodes"),)},
    {"operational_rules": (rule("n_sessions"), rule("n_sessions"))},
])
def test_invalid_configuration_rejected(changes):
    with pytest.raises(ValidationError):
        configuration(**changes)


def test_invalid_ramp_bounds_rejected():
    with pytest.raises(ValidationError):
        rule("absolute_exceedance", 4, 4)


def test_provenance_mismatch_is_rejected():
    with pytest.raises(ValueError, match="provenance_mismatch"):
        make_output(changes={"source_version": "different"})


def test_roundtrip_is_versioned_research_only_and_deterministic():
    output = make_output()
    assert output == make_output()
    assert FarmRiskOutput.model_validate_json(output.model_dump_json()) == output
    assert output.contract_version == "1.0.0"
    assert output.research_only and not output.live_warning_allowed
    assert output.model_status == "random_forest_experimental_not_live_validated"


def test_tampered_payload_cannot_enable_live_use_or_fake_complete_score():
    output = make_output(missing_climate=True)
    for update in ({"live_warning_allowed": True}, {"combined_score": 0}, {"risk_category": "low_provisional"}):
        with pytest.raises(ValidationError):
            prepare_publication(output.model_copy(update=update))


def test_publishing_requires_approval_and_uses_only_fixed_member4_object():
    calls = []
    class FakeSink:
        def insert_member4_research_v1(self, **kwargs): calls.append(kwargs)
    sink = FakeSink()
    output = make_output()
    for approval in (None, "c1_output.outlook", "core.herd_day"):
        with pytest.raises(PermissionError):
            publish_to_approved_sink(output, sink, approved_object=approval)
    assert calls == []
    publish_to_approved_sink(output, sink, approved_object=APPROVAL_OBJECT)
    assert len(calls) == 1
    assert calls[0]["target"] == "c4_output.farm_risk_assessment_v1"
    assert calls[0]["record"]["payload"]["research_only"] is True
    assert calls[0]["record"]["combined_score"] == 42.5


def test_prepare_publication_alone_has_no_side_effects():
    record = prepare_publication(make_output())
    assert record["farm_id"] == "FARM_X"
    assert record["climate_score"] == 50
    assert record["payload"]["provenance"]["availability"] == "unknown"


def test_publication_rejects_tampered_indicator_and_contribution_values():
    output = make_output()
    altered = output.model_dump(mode="json")
    altered["domains"][0]["indicators"][0]["score"] = 99
    with pytest.raises(ValidationError):
        FarmRiskOutput.model_validate(altered)
    with pytest.raises(ValidationError):
        prepare_publication(output.model_copy(update={"contributions": {"climate": 0, "biological": 0, "operational": 0}}))
