"""Read published herd aggregates for C3; no animal rows or external services."""
from datetime import timedelta
import psycopg

from .data_readiness import connection_settings

HERD_SQL = """
SELECT max(date) AS observed_date,
       max(n_herd) AS total_animals, max(milking) AS milking,
       max(dry_open + dry_pregnant) AS dry,
       max(heifers_pregnant + dry_pregnant) AS pregnant_nonmilking,
       max(unknown_state) AS unknown_state
FROM core.herd_day
WHERE date = (SELECT max(date) FROM core.herd_day)
"""

PERIOD_SQL = """
SELECT count(*) AS observed_days,
       count(*) FILTER (WHERE data_gap) AS gap_days,
       count(*) FILTER (WHERE milk_delpro_cows + milk_delpro_unidentified > 0)
           AS delpro_days,
       sum(milk_delpro_cows + milk_delpro_unidentified)
           FILTER (WHERE milk_delpro_cows + milk_delpro_unidentified > 0)
           AS delpro_litres,
       count(milk_shipped) AS shipment_days,
       sum(milk_shipped) AS shipment_litres
FROM core.herd_day WHERE date BETWEEN %(start)s AND %(end)s
"""

WEATHER_SQL = """
SELECT count(*) AS observed_days,
       count(*) FILTER (WHERE is_complete) AS complete_days,
       avg(thi_mean) AS mean_daily_thi,
       max(thi_max) AS max_hourly_thi
FROM core.weather_day WHERE date BETWEEN %(start)s AND %(end)s
"""


DAILY_MILK_SQL = """
SELECT date AS day, count(*)::integer AS source_rows,
       bool_or(data_gap) AS data_gap,
       sum(milk_delpro_cows + milk_delpro_unidentified)
           FILTER (WHERE milk_delpro_cows + milk_delpro_unidentified > 0) AS delpro_litres,
       sum(milk_shipped) AS shipments_litres
FROM core.herd_day WHERE date BETWEEN %(start)s AND %(end)s
GROUP BY date ORDER BY date
"""


def read_context(settings):
    """Read only aggregate records using the C3 login and one consistent snapshot."""
    with psycopg.connect(**settings) as conn:
        with conn.cursor() as cursor:
            cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            cursor.execute(HERD_SQL)
            herd = dict(cursor.fetchone())
            end = herd['observed_date']
            if end is None:
                raise ValueError('No published herd coverage.')
            periods = []
            for offset in (0, 7):
                bounds = dict(start=end-timedelta(days=offset+6), end=end-timedelta(days=offset))
                cursor.execute(PERIOD_SQL, bounds)
                periods.append({**bounds, **dict(cursor.fetchone())})
            cursor.execute(WEATHER_SQL, dict(start=end-timedelta(days=6), end=end))
            weather = dict(cursor.fetchone())
            cursor.execute('SELECT count(*) AS failing_months FROM core.herd_month '
                           'WHERE abs(balance_residual)>balance_tolerance OR balance_residual IS NULL')
            failures = cursor.fetchone()['failing_months']
            cursor.execute('SELECT version FROM publish.publish_log ORDER BY published_at DESC, version DESC LIMIT 1')
            published = cursor.fetchone()
            if not published:
                raise ValueError('Missing publication provenance.')
            cursor.execute(DAILY_MILK_SQL, dict(start=end-timedelta(days=13), end=end))
            daily = [dict(row) for row in cursor.fetchall()]
    return dict(herd=herd, current_period=periods[0], previous_period=periods[1],
                weather=weather, balance_failing_months=failures,
                core_version=published['version'], milk_daily=daily)
