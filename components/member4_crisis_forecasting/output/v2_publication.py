"""USER-RUN AFTER EXPLICIT APPROVAL: append-only V2, no V1 SQL."""
import json
from components.member4_crisis_forecasting.output.publisher import prepare_publication
from components.member4_crisis_forecasting.output.local_publication import COLUMNS
from components.member4_crisis_forecasting.services.v2_outputs import START, END

OBJECT = 'c4_output.farm_risk_assessment_v2'
INSERT = 'INSERT INTO c4_output.farm_risk_assessment_v2 (' + ', '.join(COLUMNS) + ') VALUES (' + ', '.join(['%s']*len(COLUMNS)) + ') ON CONFLICT (farm_id, assessment_date, scoring_version) DO NOTHING RETURNING output_id'
EXISTING = 'SELECT payload FROM c4_output.farm_risk_assessment_v2 WHERE farm_id = %s AND assessment_date = %s AND scoring_version = %s'


def semantic_payload(payload):
    if isinstance(payload, str): payload = json.loads(payload)
    from components.member4_crisis_forecasting.schemas.risk_output import validate_research_output
    result = validate_research_output(payload).model_dump(mode='json')
    return {k: v for k, v in result.items() if k not in ('generated_at', 'output_id')}


def publish_v2(outputs, *, approved_object=None, host, port, password, connect=None):
    if approved_object != OBJECT: raise PermissionError('explicit_v2_publication_approval_required')
    records = [prepare_publication(output) for output in outputs]
    keys = [(r['farm_id'], r['assessment_date'], r['scoring_version']) for r in records]
    if len(set(keys)) != len(keys): raise ValueError('duplicate_batch_dates')
    if len({r['scoring_version'] for r in records}) > 1: raise ValueError('mixed_v2_versions')
    for record in records:
        if (not START.isoformat() <= record['assessment_date'] <= END.isoformat()
                or record['contract_version'] != '1.1.0' or record['payload']['provenance']['source'] != 'published'):
            raise ValueError('unsupported_v2_record')
    if not records: return dict(inserted=0, unchanged_existing=0)
    if connect is None:
        import psycopg
        connect = psycopg.connect
    from psycopg.types.json import Jsonb
    inserted = unchanged = 0
    with connect(host=host, port=port, user='farmx_c4', dbname='farmx_app', password=password, connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            for record in records:
                cursor.execute(INSERT, tuple(Jsonb(record[c]) if c == 'payload' else record[c] for c in COLUMNS))
                if cursor.fetchone() is not None:
                    inserted += 1
                else:
                    cursor.execute(EXISTING, (record['farm_id'], record['assessment_date'], record['scoring_version']))
                    found = cursor.fetchone()
                    if found is None or semantic_payload(found[0]) != semantic_payload(record['payload']):
                        raise ValueError('existing_v2_conflict_requires_new_version_no_overwrite')
                    unchanged += 1
    return dict(inserted=inserted, unchanged_existing=unchanged)
