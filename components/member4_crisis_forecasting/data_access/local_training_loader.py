"""USER-RUN ONLY. Importing this module never imports a driver or connects."""

from components.member4_crisis_forecasting.data_access.aggregate_mapper import validate_aggregate

# Fixed allowlist: no SELECT *, discovery queries, other tables, or source records.
SELECT_APPROVED_DAYS = """
SELECT date, target_source, target_litres_per_cow, is_scoreable, milking,
       thi_mean, thi_max, hours_thi_above, mastitis_episodes,
       udder_teat_episodes, other_health_episodes, n_sessions,
       n_blood_alarms, n_conductivity_alarms
FROM model_input.day_panel
WHERE date <= %s
ORDER BY date
"""


def load_approved_days(*, host, port, password, test_end, connect=None):
    """One read-only repeatable snapshot, fixed database/role, no .env reader.

    Tests must inject a fake connection; agents must never invoke the live path.
    Errors are sanitized at the CLI boundary. No row-level exports are made.
    """
    if connect is None:
        import psycopg
        connect = psycopg.connect
    from psycopg.rows import dict_row

    with connect(
        host=host, port=port, dbname="farmx_app", user="farmx_c4", password=password,
        connect_timeout=10, row_factory=dict_row,
        options="-c default_transaction_read_only=on",
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute(SELECT_APPROVED_DAYS, (test_end,))
            return tuple(validate_aggregate(row) for row in cursor)
