"""Read-only cow-day loader for Layer 2 (``cow_layer``).

Exception to the rule in ``data.py`` that Python only receives aggregates: a cow-level
model has to fit on cow-days. To keep that as narrow as possible:

* the query replaces the pseudonym ``animal_key`` with a per-run integer
  (``DENSE_RANK``), so animal keys never leave the database;
* rows are held in memory for the run only and are never printed or written;
  callers write aggregate tables only (``cow_layer.write_layer2_outputs``);
* the session is read-only (``SqlHerdSource.from_env``) and reads ``core`` only.

One row per milking cow-day in [start, end]:

* milking interval: calving day to the day before the first of dry-off, lactation end,
  exit and the next calving (open lactations run to the next calving, exit or ``end``);
* ``litres``: the cow's valid ``core.animal_daily`` record that day (NULL when none, or
  when the cow has more than one record that day);
* records outside every milking interval are kept as milking cow-days with unknown DIM:
  ``after_dry_off`` TRUE when an earlier calving exists (missing calving or wrong
  dry-off), parity ``unknown`` when the cow has no calving at all;
* placeholder animals (herd-total records) and bad dates are excluded;
* ``days_pregnant``: days since the recorded conception of this lactation (0 before it
  or when none is recorded). Conception dates are confirmed after the fact, so this is
  descriptive information, not what was known on that day.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from .data import _IDENT


def cowday_sql(core: str) -> str:
    if not _IDENT.match(core):
        raise ValueError(f"invalid schema name: {core!r}")
    return f"""
    WITH lac AS (
        SELECT l.animal_key, l.calving_date, l.lactation_no, l.conception_date,
               LEAST(COALESCE(l.dry_off_date, 'infinity'::date),
                     COALESCE(l.end_date, 'infinity'::date),
                     COALESCE(a.exit_date, 'infinity'::date),
                     COALESCE(LEAD(l.calving_date) OVER (PARTITION BY l.animal_key
                                                         ORDER BY l.calving_date),
                              'infinity'::date)) AS milk_end
        FROM {core}.lactation l
        JOIN {core}.animal a ON a.animal_key = l.animal_key
        WHERE NOT COALESCE(l.is_bad_date, false) AND NOT COALESCE(a.is_placeholder, false)
    ), pop AS MATERIALIZED (
        SELECT lac.animal_key, g::date AS day, lac.calving_date, lac.lactation_no,
               lac.conception_date
        FROM lac
        CROSS JOIN LATERAL generate_series(
            GREATEST(lac.calving_date, CAST(:start AS date)),
            LEAST(lac.milk_end - 1, CAST(:end AS date)), interval '1 day') AS g
        WHERE lac.milk_end > CAST(:start AS date) AND lac.calving_date <= CAST(:end AS date)
    ), rec AS MATERIALIZED (
        SELECT d.animal_key, d.milk_date AS day,
               CASE WHEN COUNT(*) = 1 THEN MAX(d.yield_litres)::float END AS litres
        FROM {core}.animal_daily d
        JOIN {core}.animal a ON a.animal_key = d.animal_key
        WHERE d.is_yield_valid AND NOT COALESCE(d.is_bad_date, false)
          AND NOT COALESCE(a.is_placeholder, false) AND d.yield_litres > 0
          AND d.milk_date BETWEEN CAST(:start AS date) AND CAST(:end AS date)
        GROUP BY d.animal_key, d.milk_date
    ), outside AS (
        SELECT r.animal_key, r.day, r.litres, l.calving_date, l.lactation_no,
               l.conception_date
        FROM rec r
        LEFT JOIN LATERAL (
            SELECT calving_date, lactation_no, conception_date FROM lac
            WHERE lac.animal_key = r.animal_key AND lac.calving_date <= r.day
            ORDER BY lac.calving_date DESC LIMIT 1
        ) l ON TRUE
        WHERE NOT EXISTS (SELECT 1 FROM pop p WHERE p.animal_key = r.animal_key AND p.day = r.day)
    ), rows_ AS (
        SELECT p.animal_key, p.day, p.calving_date, p.lactation_no, p.conception_date,
               r.litres, false AS after_dry_off, true AS in_interval
        FROM pop p LEFT JOIN rec r ON r.animal_key = p.animal_key AND r.day = p.day
        UNION ALL
        SELECT animal_key, day, calving_date, lactation_no, conception_date, litres,
               calving_date IS NOT NULL, false
        FROM outside
    )
    SELECT DENSE_RANK() OVER (ORDER BY animal_key) AS cow_id,
           day AS date,
           CASE WHEN lactation_no = 1 THEN '1' WHEN lactation_no = 2 THEN '2'
                WHEN lactation_no >= 3 THEN '3+' ELSE 'unknown' END AS parity_group,
           CASE WHEN in_interval THEN day - calving_date + 1 END AS dim,
           CASE WHEN in_interval AND conception_date > calving_date AND day >= conception_date
                THEN day - conception_date ELSE 0 END AS days_pregnant,
           litres,
           after_dry_off
    FROM rows_"""


COWDAY_COLUMNS = ("animal", "date", "parity_group", "dim", "days_pregnant", "litres",
                  "after_dry_off")


def tidy_cowdays(raw: pd.DataFrame) -> pd.DataFrame:
    """Typed frame for ``cow_layer.prepare_cowdays``; refuses frames carrying animal keys."""
    if "animal_key" in raw.columns:
        raise ValueError("cow-day frame must not contain animal_key")
    f = raw.rename(columns={"cow_id": "animal"})
    f["animal"] = f["animal"].astype("int64")
    f["date"] = pd.to_datetime(f["date"])
    f["parity_group"] = f["parity_group"].astype(str)
    f["dim"] = pd.to_numeric(f["dim"], errors="coerce").astype("float64")
    f["days_pregnant"] = pd.to_numeric(f["days_pregnant"], errors="coerce").fillna(0).astype("float64")
    f["litres"] = pd.to_numeric(f["litres"], errors="coerce").astype("float64")
    f["after_dry_off"] = f["after_dry_off"].astype("boolean").fillna(False).astype(bool)
    return f[list(COWDAY_COLUMNS)].sort_values(["date", "animal"]).reset_index(drop=True)


def load_cowdays(source, start: date, end: date) -> pd.DataFrame:
    """Milking cow-days from ``source`` (a ``SqlHerdSource``); see the module docstring."""
    raw = source._q(cowday_sql(source.core), start=start, end=end)
    return tidy_cowdays(raw)
