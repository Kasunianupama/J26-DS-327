"""Fixed-object publishing seam; no driver, connection, migrations, or SQL execution."""

from typing import Protocol

from components.member4_crisis_forecasting.schemas.risk_output import FarmRiskOutput, validate_research_output

APPROVAL_OBJECT = "c4_output.farm_risk_assessment_v1"


class ResearchOutputSink(Protocol):
    """Future reviewed adapter must implement append-only insertion to this object.

    There is deliberately no arbitrary SQL/schema/table method or production
    adapter. Supplying a sink is a user-controlled side effect, never automatic.
    """

    def insert_member4_research_v1(self, *, target: str, record: dict) -> None: ...


def prepare_publication(output: FarmRiskOutput) -> dict:
    """Revalidate even model_construct/model_copy outputs before serialization."""
    validated = validate_research_output(output.model_dump(mode="json"))
    payload = validated.model_dump(mode="json")
    by_domain = {item.domain: item.score for item in validated.domains}
    return dict(output_id=str(validated.output_id), contract_version=validated.contract_version,
                farm_id=validated.farm_id, assessment_date=validated.assessment_date.isoformat(),
                assessment_cutoff=validated.assessment_cutoff.isoformat() if validated.assessment_cutoff is not None else None,
                generated_at=validated.generated_at.isoformat(),
                score_basis=getattr(validated, "score_basis", "quality_gated"),
                scoring_version=validated.scoring_config.version, research_only=True, live_warning_allowed=False,
                model_status=validated.model_status, climate_score=by_domain["climate"],
                biological_score=by_domain["biological"], operational_score=by_domain["operational"],
                combined_score=validated.combined_score, risk_category=validated.risk_category,
                data_completeness=validated.data_completeness, payload=payload)


def publish_to_approved_sink(output, sink: ResearchOutputSink, *, approved_object: str | None = None):
    """Disabled unless caller explicitly names the reviewed object; no live adapter.

    Tests use a memory-only fake sink. This function is NOT called on import,
    scoring, or prepare_publication. No retries/upserts/deletes are performed.
    """
    if approved_object != APPROVAL_OBJECT:
        raise PermissionError("member4_output_object_requires_explicit_approval")
    record = prepare_publication(output)
    sink.insert_member4_research_v1(target=APPROVAL_OBJECT, record=record)
