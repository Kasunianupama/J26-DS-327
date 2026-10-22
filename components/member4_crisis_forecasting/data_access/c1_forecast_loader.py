"""USER-RUN ONLY: fixed C1 output SELECT. No C1 internal imports or fallback demo."""
SELECT_C1 = """
SELECT origin_date, target_period, grain, horizon, series, forecast, lower, upper,
       quality_flag, model_version, core_version, created_at
FROM c1_output.outlook
WHERE origin_date = %s AND model_version = %s
  AND grain = 'daily' AND series = 'herd_milk'
ORDER BY target_period, horizon
"""


def load_c1_forecasts(*, host, port, password, origin_date, model_version, connect=None):
    if connect is None:
        import psycopg
        connect = psycopg.connect
    from psycopg.rows import dict_row
    with connect(host=host, port=port, dbname="farmx_app", user="farmx_c4",
                 password=password, connect_timeout=10, row_factory=dict_row,
                 options="-c default_transaction_read_only=on") as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute(SELECT_C1, (origin_date, model_version))
            return tuple(dict(row) for row in cursor)
