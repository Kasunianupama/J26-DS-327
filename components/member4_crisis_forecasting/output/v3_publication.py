"""Explicitly approved append-only V3 only; source outputs never mutated."""
import json
from components.member4_crisis_forecasting.schemas.v3_output import V3Output

OBJECT = 'c4_output.farm_risk_assessment_v3'
COLUMNS = ('output_id','farm_id','assessment_date','contract_version','generated_at','scoring_version',
           'source_output_id','source_payload_sha256','research_only','live_warning_allowed','model_status',
           'climate_score','operational_score','combined_score','risk_category','data_completeness','payload')
SELECT_V3 = 'SELECT '+', '.join(COLUMNS)+' FROM c4_output.farm_risk_assessment_v3 WHERE farm_id = :farm_id ORDER BY assessment_date, output_id'
INSERT = 'INSERT INTO c4_output.farm_risk_assessment_v3 ('+', '.join(COLUMNS)+') VALUES ('+', '.join(['%s']*len(COLUMNS))+') ON CONFLICT (farm_id, assessment_date, scoring_version) DO NOTHING RETURNING output_id'
EXISTING = 'SELECT payload FROM c4_output.farm_risk_assessment_v3 WHERE farm_id=%s AND assessment_date=%s AND scoring_version=%s'


def prepare_v3(output):
    model = V3Output.model_validate(output.model_dump(mode='json'))
    payload = model.model_dump(mode='json')
    record = {key: payload[key] for key in COLUMNS if key in payload and key != 'payload'}
    record.update(scoring_version=model.scoring_config.version, climate_score=model.domains[0].score,
                  operational_score=model.domains[1].score, payload=payload)
    return record


def semantic_v3(payload):
    if isinstance(payload, str): payload = json.loads(payload)
    validated = V3Output.model_validate(payload).model_dump(mode='json')
    return {key: value for key, value in validated.items() if key not in ('output_id','generated_at')}


def publish_v3(outputs, *, approved_object=None, host, port, password, connect=None):
    if approved_object != OBJECT: raise PermissionError('explicit_v3_publication_approval_required')
    records = [prepare_v3(o) for o in outputs]
    if len({r['assessment_date'] for r in records}) != len(records): raise ValueError('duplicate_v3_dates')
    if not records: return dict(inserted=0, unchanged_existing=0)
    if connect is None:
        import psycopg
        connect = psycopg.connect
    from psycopg.types.json import Jsonb
    inserted = unchanged = 0
    with connect(host=host, port=port, dbname='farmx_app', user='farmx_c4', password=password, connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            for record in records:
                cursor.execute(INSERT, tuple(Jsonb(record[c]) if c=='payload' else record[c] for c in COLUMNS))
                if cursor.fetchone() is not None: inserted += 1
                else:
                    cursor.execute(EXISTING, (record['farm_id'],record['assessment_date'],record['scoring_version']))
                    existing = cursor.fetchone()
                    if existing is None or semantic_v3(existing[0]) != semantic_v3(record['payload']):
                        raise ValueError('conflicting_v3_payload_no_overwrite')
                    unchanged += 1
    return dict(inserted=inserted, unchanged_existing=unchanged)
