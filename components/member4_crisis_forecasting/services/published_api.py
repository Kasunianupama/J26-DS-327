"""Validated published outputs only. Lazy database access; never demo fallback."""
import json
import os
from datetime import datetime

from sqlalchemy import text

from components.member4_crisis_forecasting.output.publisher import prepare_publication
from components.member4_crisis_forecasting.schemas.risk_output import validate_research_output
from components.member4_crisis_forecasting.prediction.research_prediction import ResearchPrediction


class PublishedUnavailable(Exception):
    pass


class StoredContractMismatch(Exception):
    pass


# Fixed allowlist: no caller-controlled identifiers and no other objects.
QUERIES = {
    "assessments": "SELECT output_id, farm_id, assessment_date, contract_version, research_only, live_warning_allowed, model_status, score_basis, scoring_version, climate_score, biological_score, operational_score, combined_score, risk_category, data_completeness, assessment_cutoff, generated_at, payload FROM c4_output.farm_risk_assessment_v1 WHERE farm_id = :farm_id ORDER BY assessment_date, output_id",
    "predictions": "SELECT prediction_id, farm_id, assessment_date, contract_version, research_only, live_warning_allowed, model_status, artifact_version, artifact_sha256, predicted_decline_probability, saved_threshold, predicted_decline, classification_status, actual_outcome, outcome_reason, experiment_partition, milk_source, historical_availability, recording_completeness, probability_interpretation, generated_at, payload FROM c4_output.milk_decline_prediction_v1 WHERE farm_id = :farm_id ORDER BY assessment_date, prediction_id",
}
QUERIES['assessments_v2'] = QUERIES['assessments'].replace('c4_output.farm_risk_assessment_v1', 'c4_output.farm_risk_assessment_v2')
from components.member4_crisis_forecasting.output.v3_publication import SELECT_V3, prepare_v3
from components.member4_crisis_forecasting.schemas.v3_output import V3Output
QUERIES['assessments_v3'] = SELECT_V3


def validate_record(kind, row):
    """Recheck full Python contract AND denormalized stored columns, never repair."""
    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise ValueError("payload_not_object")
    # Reject coercible false/true/string flag values before Pydantic conversion.
    if payload.get("research_only") is not True or payload.get("live_warning_allowed") is not False:
        raise ValueError("invalid_research_flags")
    if kind == 'assessments_v3':
        model = V3Output.model_validate(payload)
        expected = prepare_v3(model)
    elif kind in ("assessments", "assessments_v2"):
        model = validate_research_output(payload)
        if model.provenance.source != "published" or model.assessment_date.year not in (2025, 2026):
            raise ValueError("unsupported_assessment_scope_or_source")
        expected = prepare_publication(model)
        if kind == 'assessments_v2' and (model.contract_version != '1.1.0' or not '2026-01-01' <= model.assessment_date.isoformat() <= '2026-08-20'):
            raise ValueError('unsupported_v2_scope')
    else:
        model = ResearchPrediction.model_validate(payload)
        if model.assessment_date.year != 2022:
            raise ValueError("unsupported_experiment_period")
        expected = model.model_dump(mode="json")
    for name, value in row.items():
        if name == "payload":
            continue
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        elif name in ("output_id", "prediction_id", "source_output_id"):
            value = str(value)
        wanted = expected.get(name)
        # PostgreSQL datetime objects and Pydantic JSON use equivalent +00:00/Z
        # spellings. Compare instants without changing returned provenance.
        if name in ("generated_at", "assessment_cutoff") and value is not None and wanted is not None:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            wanted = datetime.fromisoformat(wanted.replace("Z", "+00:00"))
        if name not in expected or value != wanted:
            raise ValueError("stored_column_payload_mismatch")
    return model.model_dump(mode="json")


class PublishedOutputService:
    def __init__(self, engine_factory=None, enabled=None):
        self.engine_factory = engine_factory
        self.enabled = enabled

    def read(self, kind, farm_id):
        if farm_id != "FARM_X" or kind not in QUERIES:
            raise ValueError("unsupported_scope")
        enabled = self.enabled if self.enabled is not None else os.environ.get("C4_RESEARCH_DB") == "on"
        if not enabled:
            raise PublishedUnavailable("published_reads_disabled")
        try:
            if self.engine_factory is None:
                from backend.app.database.connection import create_app_database_engine
                factory = create_app_database_engine
            else:
                factory = self.engine_factory
            engine = factory()
            try:
                with engine.connect() as connection:
                    with connection.begin():
                        connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
                        rows = [dict(row) for row in connection.execute(text(QUERIES[kind]), {"farm_id": farm_id}).mappings()]
            finally:
                engine.dispose()
        except Exception:
            raise PublishedUnavailable("published_database_unavailable") from None
        try:
            items = [validate_record(kind, row) for row in rows]
            key = "output_id" if kind.startswith('assessments') else "prediction_id"
            if kind in ('assessments_v2', 'assessments_v3'):
                if len({item['scoring_config']['version'] for item in items}) > 1:
                    raise ValueError('mixed_v2_scoring_versions')
                if len({item['assessment_date'] for item in items}) != len(items):
                    raise ValueError('duplicate_v2_dates')
                if kind == 'assessments_v3' and len({item['scoring_config']['source_scoring_version'] for item in items}) > 1:
                    raise ValueError('mixed_v3_source_scoring_versions')
            if len({item[key] for item in items}) != len(items):
                raise ValueError("duplicate_output_ids")
            items.sort(key=lambda item: (item["assessment_date"], item[key]))
        except Exception:
            raise StoredContractMismatch("stored_member4_contract_mismatch") from None
        return {"source": "published", "contract_version": "1.0.0", "items": items}


published_output_service = PublishedOutputService()
