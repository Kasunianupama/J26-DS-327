"""Read-only, aggregate-only readiness check for C3's published Farm X inputs."""
import json
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


SUMMARY_SQL = """
SELECT count(*) AS herd_days,
       min(h.date) AS first_date, max(h.date) AS last_date,
       count(*) FILTER (WHERE h.data_gap) AS milk_gap_days,
       count(*) FILTER (WHERE w.date IS NULL) AS missing_weather_days,
       count(*) FILTER (WHERE w.date IS NOT NULL AND NOT w.is_complete)
           AS incomplete_weather_days,
       min(w.temp_min_c) AS temperature_min_c,
       max(w.temp_max_c) AS temperature_max_c,
       avg(w.thi_mean) AS mean_daily_thi,
       has_schema_privilege(current_user, 'c3_output', 'CREATE')
           AS can_create_outputs
FROM core.herd_day h
LEFT JOIN core.weather_day w ON w.date = h.date
"""


def connection_settings(environ=None):
    """Use C3 credentials only; never fall back to the backend or admin login."""
    env = os.environ if environ is None else environ
    if env.get('APP_DB_NAME') != 'farmx_app':
        raise ValueError('APP_DB_NAME must be farmx_app.')
    if env.get('APP_DB_C3_USER') != 'farmx_c3':
        raise ValueError('APP_DB_C3_USER must be farmx_c3.')
    if not env.get('APP_DB_C3_PASSWORD'):
        raise ValueError('APP_DB_C3_PASSWORD is required.')
    return dict(host=env.get('APP_DB_HOST', 'localhost'),
                port=int(env.get('APP_DB_PORT', '5432')),
                dbname='farmx_app', user='farmx_c3',
                password=env['APP_DB_C3_PASSWORD'], connect_timeout=10,
                options='-c default_transaction_read_only=on -c statement_timeout=30000',
                row_factory=dict_row)


def read_summary(settings):
    """Return one aggregate record from one read-only, consistent transaction."""
    with psycopg.connect(**settings) as conn:
        with conn.cursor() as cursor:
            cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            cursor.execute(SUMMARY_SQL)
            summary = dict(cursor.fetchone())
            cursor.execute('SELECT version FROM publish.publish_log '
                           'ORDER BY published_at DESC, version DESC LIMIT 1')
            version = cursor.fetchone()
            summary['core_version'] = version['version'] if version else None
    return summary


def main():
    # Only an explicit human-run CLI invocation loads the project's private .env.
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[3] / '.env', override=False)
    try:
        settings = connection_settings()
    except (ValueError, TypeError):
        print('C3 settings invalid: check APP_DB_NAME and APP_DB_C3_* privately.')
        return 1
    try:
        summary = read_summary(settings)
    except Exception:
        # Driver exceptions can include connection details; never print them.
        print('C3 check failed: check connection, permissions and published tables locally.')
        return 1
    print(json.dumps(summary, default=str, indent=2, allow_nan=False))
    return 0 if summary['herd_days'] > 0 and summary['can_create_outputs'] and summary['core_version'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
