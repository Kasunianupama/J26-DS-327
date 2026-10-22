"""Future approved append-only prediction publication; never assessment writes."""

from components.member4_crisis_forecasting.prediction.research_prediction import ResearchPrediction

PREDICTION_OBJECT = "c4_output.milk_decline_prediction_v1"
COLUMNS = ("prediction_id", "contract_version", "farm_id", "assessment_date", "generated_at", "artifact_version",
           "artifact_sha256", "model_status", "research_only", "live_warning_allowed", "predicted_decline_probability",
           "saved_threshold", "predicted_decline", "classification_status", "actual_outcome", "outcome_reason",
           "experiment_partition", "milk_source", "historical_availability", "recording_completeness",
           "probability_interpretation", "payload")
INSERT_PREDICTION = "INSERT INTO c4_output.milk_decline_prediction_v1 (" + ", ".join(COLUMNS) + ") VALUES (" + ", ".join(["%s"] * len(COLUMNS)) + ")"


def publish_approved_predictions(outputs, *, approved_object=None, host, port, password, connect=None):
    if approved_object != PREDICTION_OBJECT:
        raise PermissionError("separate_prediction_table_approval_required")
    records = []
    for output in outputs:
        payload = ResearchPrediction.model_validate(output.model_dump(mode="json")).model_dump(mode="json")
        records.append({**{column: payload[column] for column in COLUMNS if column != "payload"}, "payload": payload})
    if len({record["prediction_id"] for record in records}) != len(records):
        raise ValueError("duplicate_prediction_ids")
    if not records:
        return 0
    if connect is None:
        import psycopg
        connect = psycopg.connect
    from psycopg.types.json import Jsonb
    with connect(host=host, port=port, user="farmx_c4", dbname="farmx_app", password=password, connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            for record in records:
                values = tuple(Jsonb(record[column]) if column == "payload" else record[column] for column in COLUMNS)
                cursor.execute(INSERT_PREDICTION, values)
    return len(records)
