"""Read one unambiguous stored C1 forecast through aggregate-only local SQL."""
import psycopg
from .c4_repository import private_settings

FORECAST_SQL = """
SELECT count(*)::integer AS forecast_count,
       count(DISTINCT core_version)::integer AS version_count,
       max(core_version) AS core_version, max(origin_date) AS origin_date,
       max(forecast) AS forecast, max(lower) AS lower, max(upper) AS upper,
       array_agg(DISTINCT quality_flag) FILTER (WHERE quality_flag IS NOT NULL) AS quality_flags
FROM c1_output.outlook
WHERE model_version = %(model_version)s AND grain = %(grain)s AND series = %(series)s
  AND target_period = %(target_period)s AND origin_date <= %(reference_date)s
  AND origin_date = COALESCE(%(origin_date)s::date, (
      SELECT max(origin_date) FROM c1_output.outlook
      WHERE model_version = %(model_version)s AND grain = %(grain)s AND series = %(series)s
        AND target_period = %(target_period)s AND origin_date <= %(reference_date)s))
"""


def read_forecast(arguments, settings=None):
    """Do not merge runs, select a different model or infer absent ranges."""
    with psycopg.connect(**(private_settings() if settings is None else settings)) as conn:
        with conn.cursor() as cursor:
            cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            cursor.execute(FORECAST_SQL, arguments.model_dump())
            row = dict(cursor.fetchone())
    if row.pop('forecast_count') != 1 or row.pop('version_count') != 1:
        raise ValueError('No unique forecast with known source provenance.')
    row['quality_flags'] = row['quality_flags'] or []
    return dict(kind='c1_forecast', demo=False, model_version=arguments.model_version,
                target_period=arguments.target_period, grain=arguments.grain,
                series=arguments.series, **row)
