"""USER-RUN: V2 snapshot to V3 verification; writes require explicit approval."""
import argparse
from datetime import datetime, timezone
from getpass import GetPassWarning, getpass
import json
import os
import sys
import warnings
from components.member4_crisis_forecasting.services.v3_outputs import generate_v3
from components.member4_crisis_forecasting.output.v3_publication import OBJECT, semantic_v3


def load_source(*, host, port, password, include_v3=False, connect=None):
    from components.member4_crisis_forecasting.services.published_api import QUERIES, validate_record
    if connect is None:
        import psycopg
        connect = psycopg.connect
    from psycopg.rows import dict_row
    data = {}
    with connect(host=host, port=port, dbname='farmx_app', user='farmx_c4', password=password,
                 row_factory=dict_row, connect_timeout=10, options='-c default_transaction_read_only=on') as connection:
        with connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            for kind in (('assessments_v2','assessments_v3') if include_v3 else ('assessments_v2',)):
                cursor.execute(QUERIES[kind].replace(':farm_id','%s'), ('FARM_X',))
                data[kind] = [validate_record(kind, dict(row)) for row in cursor]
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publish-approved', action='store_true')
    parser.add_argument('--approved-object')
    parser.add_argument('--verify-published', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.publish_approved != (args.approved_object == OBJECT) or (args.approved_object and not args.publish_approved) or (args.verify_published and args.publish_approved):
            raise ValueError('separate_explicit_verification_or_publication_required')
        if not sys.stdin.isatty(): raise ValueError('interactive_terminal_required')
        with warnings.catch_warnings():
            warnings.simplefilter('error', GetPassWarning)
            password = getpass('Local farmx_c4 password (hidden): ')
        host, port = os.environ.get('C4_DB_HOST','localhost'), int(os.environ.get('C4_DB_PORT','5432'))
        data = load_source(host=host, port=port, password=password, include_v3=args.verify_published)
        outputs, summary = generate_v3(data['assessments_v2'], generated_at=datetime.now(timezone.utc))
        if args.verify_published:
            expected = {o.assessment_date.isoformat(): semantic_v3(o.model_dump(mode='json')) for o in outputs}
            actual = data['assessments_v3']
            if len({o['assessment_date'] for o in actual}) != len(actual): raise ValueError('duplicate_published_v3_dates')
            matching = sum(expected.get(o['assessment_date']) == semantic_v3(o) for o in actual)
            summary['published_verification'] = dict(stored_count=len(actual), matching_count=matching,
                complete_match=bool(expected) and len(expected)==len(actual)==matching)
        if args.publish_approved:
            if summary['missing_calendar_days'] != 0:
                raise ValueError('full_232_day_source_required_before_publication')
            from components.member4_crisis_forecasting.output.v3_publication import publish_v3
            summary['publication'] = publish_v3(outputs, approved_object=args.approved_object, host=host, port=port, password=password)
        del password
        print(json.dumps(summary, allow_nan=False, indent=2))
        return 0 if not args.verify_published or summary['published_verification']['complete_match'] else 2
    except KeyboardInterrupt:
        print(json.dumps({'status':'cancelled'})); return 130
    except Exception:
        print(json.dumps({'status':'v3_workflow_failed','reason':'Review V2 source contract/rules, read permissions, V3 readiness or conflicting published payloads locally. No rows or credentials printed.'})); return 2


if __name__ == '__main__': main()
