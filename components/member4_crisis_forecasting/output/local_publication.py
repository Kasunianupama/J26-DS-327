"""USER-RUN AFTER APPROVAL ONLY: fixed-table append-only transaction."""

from components.member4_crisis_forecasting.output.publisher import APPROVAL_OBJECT, prepare_publication

COLUMNS = (
    "output_id", "contract_version", "farm_id", "assessment_date", "assessment_cutoff", "generated_at",
    "score_basis", "scoring_version", "research_only", "live_warning_allowed", "model_status",
    "climate_score", "biological_score", "operational_score", "combined_score", "risk_category", "data_completeness", "payload",
)
INSERT_RESEARCH = "INSERT INTO c4_output.farm_risk_assessment_v1 (" + ", ".join(COLUMNS) + ") VALUES (" + ", ".join(["%s"] * len(COLUMNS)) + ")"


def publish_approved_batch(outputs, *, approved_object=None, host, port, password, connect=None):
    if approved_object != APPROVAL_OBJECT:
        raise PermissionError("explicit_member4_table_approval_required")
    # Validate the entire batch before opening a write-capable connection.
    records = [prepare_publication(output) for output in outputs]
    if not records:
        return 0
    if len({record["output_id"] for record in records}) != len(records):
        raise ValueError("duplicate_output_ids")
    if any(set(record) != set(COLUMNS) for record in records):
        raise ValueError("publication_columns_mismatch")
    if connect is None:
        import psycopg
        connect = psycopg.connect
    from psycopg.types.json import Jsonb
    with connect(host=host, port=port, user="farmx_c4", dbname="farmx_app", password=password,
                 connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            for record in records:
                values = tuple(Jsonb(record[column]) if column == "payload" else record[column] for column in COLUMNS)
                cursor.execute(INSERT_RESEARCH, values)
    # No DDL, permission queries, retries, upserts, updates, deletes or schema selection.
    return len(records)
