"""Read-only, aggregate-only loaders for the herd engine.

* Connects to PostgreSQL ``farmx_app`` with settings from environment variables
  (``config.DatabaseSettings``); every session is opened read-only.
* Reads only ``core`` and ``model_input``. Every query aggregates in SQL, so Python
  never receives animal keys or animal-level rows.
* Every query takes the origin and filters to dates before it, and returns a
  ``max_date`` column. ``check_before`` raises ``LeakageError`` if any frame contains a
  date on or after its bound, so a wrong query fails loudly instead of leaking.

Leakage rules (docs/forecast_design.md, section 3):
* rates and distributions: facts dated in [window start, origin);
* conceptions count as known only once ``pregnancy_check_lag_days`` have passed, so
  conception-based statistics stop at ``known_until = origin - lag``;
* the starting herd is ``day_cell`` on the day before the origin.

Known caveat, documented for the user check: pregnancy states in ``day_cell`` and
``core.lactation.conception_date`` come from the ETL; if the ETL back-dates conceptions
from later calvings, part of the "known pregnancy" information is hindsight.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .categories import EVENT_COLUMNS, STOCK_COLUMNS
from .config import DatabaseSettings, EngineConfig
from .herd_engine import OriginState
from .origin_state import build_origin_state
from .rates import RateInputs, conception_per_ai, max_live_gestation

DATA_START = date(2015, 8, 1)


class LeakageError(RuntimeError):
    """An input frame contains information dated on or after the origin."""


def check_before(frame: pd.DataFrame, bound: date, name: str) -> pd.DataFrame:
    """Raise if ``frame.max_date`` reaches ``bound``; return the frame without it."""
    if "max_date" not in frame.columns:
        raise LeakageError(f"{name}: query must return max_date for the leakage guard")
    dates = pd.to_datetime(frame["max_date"], errors="coerce").dropna()
    if len(dates) and dates.max().date() >= bound:
        raise LeakageError(f"{name}: uses data dated on/after {bound.isoformat()}")
    return frame.drop(columns="max_date")


def month_start(d: date) -> date:
    return d.replace(day=1)


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    return date(d.year + y, m + 1, 1)


def window_start(origin: date, window_months: int | None) -> date:
    if window_months is None:
        return DATA_START
    return max(DATA_START, add_months(month_start(origin), -window_months))


class HerdSource(Protocol):
    """What the engine needs from the database. Each method returns aggregates."""

    def cells_on(self, asof: date) -> pd.DataFrame: ...
    def exposure(self, start: date, origin: date) -> pd.DataFrame: ...
    def transitions(self, start: date, month_end: date) -> pd.DataFrame: ...
    def panel_months(self, start: date, origin: date) -> pd.DataFrame: ...
    def cow_open(self, start: date, known_until: date) -> pd.DataFrame: ...
    def preg_milking_days(self, start: date, known_until: date, origin: date) -> pd.DataFrame: ...
    def dryoff_gest(self, start: date, known_until: date, origin: date) -> pd.DataFrame: ...
    def gestation(self, start: date, origin: date) -> pd.DataFrame: ...
    def milking_clock(self, asof: date, known_until: date) -> pd.DataFrame: ...
    def dry_clock(self, asof: date, known_until: date) -> pd.DataFrame: ...
    def heifer_clock(self, asof: date, known_until: date, lag_days: int) -> pd.DataFrame: ...
    def young_days(self, start: date, origin: date) -> pd.DataFrame: ...
    def young_exits(self, start: date, origin: date) -> pd.DataFrame: ...
    def births_by_sex(self, start: date, origin: date) -> pd.DataFrame: ...
    def calf_sex_on(self, asof: date) -> pd.DataFrame: ...
    def panel_daily(self, start: date, end: date) -> pd.DataFrame: ...


@dataclass
class OriginInputs:
    origin: date
    state: OriginState
    rate_inputs: RateInputs
    notes: list[str]


def load_origin_inputs(source: HerdSource, origin: date, cfg: EngineConfig) -> OriginInputs:
    """Everything the engine needs at ``origin``, with the leakage guard applied."""
    if origin <= DATA_START + timedelta(days=31):
        raise ValueError("origin too early: no history before it")
    asof = origin - timedelta(days=1)
    known_until = origin - timedelta(days=cfg.pregnancy_check_lag_days)
    ws = window_start(origin, cfg.window_months)
    tr_end = month_start(origin)

    preg = check_before(source.preg_milking_days(ws, known_until, origin), origin, "preg_milking_days")
    rate_inputs = RateInputs(
        origin=origin,
        window_start=ws,
        exposure=check_before(source.exposure(ws, origin), origin, "exposure"),
        transitions=check_before(source.transitions(ws, tr_end), origin, "transitions"),
        panel=check_before(source.panel_months(ws, origin), origin, "panel_months"),
        cow_open=check_before(source.cow_open(ws, known_until), known_until, "cow_open"),
        preg_milking_days=float(preg["preg_milking_days"].fillna(0).sum()) if len(preg) else 0.0,
        dryoff_gest=check_before(source.dryoff_gest(ws, known_until, origin), origin, "dryoff_gest"),
        gestation=check_before(source.gestation(ws, origin), origin, "gestation"),
        young_days=check_before(source.young_days(ws, origin), origin, "young_days"),
        young_exits=check_before(source.young_exits(ws, origin), origin, "young_exits"),
        births_by_sex=check_before(source.births_by_sex(ws, origin), origin, "births_by_sex"),
    )

    cells = check_before(source.cells_on(asof), origin, "cells_on")
    if cells["n"].sum() <= 0:
        raise ValueError(f"no day_cell rows on {asof.isoformat()}")
    milking_clock = check_before(source.milking_clock(asof, known_until), origin, "milking_clock")
    dry_clock = check_before(source.dry_clock(asof, known_until), origin, "dry_clock")
    heifer_clock = check_before(
        source.heifer_clock(asof, known_until, cfg.pregnancy_check_lag_days),
        known_until, "heifer_clock",
    )
    calf_sex = check_before(source.calf_sex_on(asof), origin, "calf_sex_on")
    state, notes = build_origin_state(
        origin, cells, milking_clock, dry_clock, heifer_clock, cfg.pregnancy_check_lag_days,
        calf_sex=calf_sex,
        max_live_gest=max_live_gestation(rate_inputs.gestation),
        conception_per_ai=conception_per_ai(rate_inputs),
    )
    return OriginInputs(origin=origin, state=state, rate_inputs=rate_inputs, notes=notes)


# --------------------------------------------------------------------------- SQL

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")

_PARITY = (
    "CASE WHEN l.lactation_no = 1 THEN '1' WHEN l.lactation_no = 2 THEN '2' "
    "WHEN l.lactation_no >= 3 THEN '3+' ELSE 'unknown' END"
)
_GENERATION = (
    "CASE WHEN a.generation IS NULL THEN 'unknown' WHEN a.generation >= 3 THEN '3+' "
    "ELSE a.generation::text END"
)
_BANDS = (
    "bands(dim_band, lo, hi) AS (VALUES ('0-60', 0, 60), ('61-150', 61, 150), "
    "('151-305', 151, 305), ('305+', 306, 100000))"
)


def _lac_cte(core: str) -> str:
    """One row per lactation, with dates needed by the cow statistics.

    ``conc`` is the conception after this calving, kept only if dated before
    ``known_until``; ``milk_end`` is the first of dry-off, lactation end and exit.
    """
    return f"""
    lac AS (
        SELECT l.animal_key,
               l.calving_date,
               l.dry_off_date,
               l.cycle_end_date,
               a.exit_date,
               {_PARITY} AS parity_group,
               {_GENERATION} AS generation_group,
               LEAST(COALESCE(l.dry_off_date, 'infinity'::date),
                     COALESCE(l.end_date, 'infinity'::date),
                     COALESCE(a.exit_date, 'infinity'::date)) AS milk_end,
               CASE WHEN l.conception_date > l.calving_date
                         AND l.conception_date < CAST(:known_until AS date)
                    THEN l.conception_date END AS conc
        FROM {core}.lactation l
        LEFT JOIN {core}.animal a ON a.animal_key = l.animal_key
        WHERE COALESCE(l.is_bad_date, false) = false
    )"""


class SqlHerdSource:
    """``HerdSource`` backed by PostgreSQL ``farmx_app`` (read-only sessions)."""

    def __init__(self, engine: Engine, settings: DatabaseSettings):
        for schema in (settings.core_schema, settings.model_input_schema):
            if not _IDENT.match(schema):
                raise ValueError(f"invalid schema name: {schema!r}")
        self.engine = engine
        self.core = settings.core_schema
        self.mi = settings.model_input_schema

    @classmethod
    def from_env(cls) -> "SqlHerdSource":
        settings = DatabaseSettings.from_env()
        engine = create_engine(
            settings.url,
            connect_args={"options": "-c default_transaction_read_only=on"},
            pool_pre_ping=True,
        )
        return cls(engine, settings)

    def _q(self, sql: str, **params) -> pd.DataFrame:
        with self.engine.connect() as conn:
            return pd.read_sql(text(sql), conn, params=params)

    # starting herd --------------------------------------------------------
    def cells_on(self, asof: date) -> pd.DataFrame:
        return self._q(
            f"""SELECT state, parity_group, dim_band, generation_group,
                       SUM(n_animals)::float AS n, MAX(date) AS max_date
                FROM {self.mi}.day_cell WHERE date = CAST(:asof AS date)
                GROUP BY 1, 2, 3, 4""",
            asof=asof,
        )

    def milking_clock(self, asof: date, known_until: date) -> pd.DataFrame:
        # recent_ai_gest: days since the last insemination after calving, for cows with
        # no conception known yet whose last service falls within the pregnancy-check
        # lag. Insemination dates are known at once, so this carries no hindsight.
        return self._q(
            f"""WITH {_lac_cte(self.core)},
                cur AS (
                    SELECT lac.*,
                           (SELECT MAX(i.insemination_date)
                            FROM {self.core}.insemination i
                            WHERE i.animal_key = lac.animal_key
                              AND i.insemination_date > lac.calving_date
                              AND i.insemination_date >= CAST(:known_until AS date)
                              AND i.insemination_date <= CAST(:asof AS date)
                              AND COALESCE(i.is_bad_date, false) = false) AS recent_ai
                    FROM lac
                    WHERE calving_date <= CAST(:asof AS date)
                      AND milk_end > CAST(:asof AS date)
                )
                SELECT parity_group, generation_group,
                       (CAST(:asof AS date) - calving_date) AS dim,
                       CASE WHEN conc <= CAST(:asof AS date)
                            THEN (CAST(:asof AS date) - conc) END AS gest,
                       CASE WHEN conc IS NULL AND recent_ai IS NOT NULL
                            THEN (CAST(:asof AS date) - recent_ai) END AS recent_ai_gest,
                       COUNT(*)::float AS n,
                       MAX(GREATEST(calving_date, conc, recent_ai)) AS max_date
                FROM cur
                GROUP BY 1, 2, 3, 4, 5""",
            asof=asof, known_until=known_until,
        )

    def dry_clock(self, asof: date, known_until: date) -> pd.DataFrame:
        return self._q(
            f"""WITH {_lac_cte(self.core)}
                SELECT parity_group, generation_group,
                       CASE WHEN conc <= CAST(:asof AS date)
                            THEN (CAST(:asof AS date) - conc) END AS gest,
                       COUNT(*)::float AS n,
                       MAX(GREATEST(dry_off_date, conc)) AS max_date
                FROM lac
                WHERE dry_off_date <= CAST(:asof AS date)
                  AND COALESCE(cycle_end_date, 'infinity'::date) > CAST(:asof AS date)
                  AND COALESCE(exit_date, 'infinity'::date) > CAST(:asof AS date)
                GROUP BY 1, 2, 3""",
            asof=asof, known_until=known_until,
        )

    def heifer_clock(self, asof: date, known_until: date, lag_days: int) -> pd.DataFrame:
        # Shape only: days since the last insemination of heifers not yet calved.
        # Uses no outcome or later calving, so it carries no hindsight.
        return self._q(
            f"""WITH last_ai AS (
                    SELECT i.animal_key, MAX(i.insemination_date) AS ai_date
                    FROM {self.core}.insemination i
                    WHERE i.insemination_date < CAST(:known_until AS date)
                      AND COALESCE(i.is_bad_date, false) = false
                    GROUP BY i.animal_key
                )
                SELECT {_GENERATION} AS generation_group,
                       (CAST(:asof AS date) - la.ai_date) AS gest,
                       COUNT(*)::float AS n, MAX(la.ai_date) AS max_date
                FROM last_ai la
                JOIN {self.core}.animal a ON a.animal_key = la.animal_key
                WHERE COALESCE(a.exit_date, 'infinity'::date) > CAST(:asof AS date)
                  AND NOT EXISTS (
                      SELECT 1 FROM {self.core}.lactation l
                      WHERE l.animal_key = la.animal_key
                        AND l.calving_date <= CAST(:asof AS date))
                  AND (CAST(:asof AS date) - la.ai_date) BETWEEN :lag AND 300
                GROUP BY 1, 2""",
            asof=asof, known_until=known_until, lag=lag_days,
        )

    # rate inputs ----------------------------------------------------------
    def exposure(self, start: date, origin: date) -> pd.DataFrame:
        return self._q(
            f"""SELECT date_trunc('month', date)::date AS month, state, parity_group,
                       dim_band, generation_group,
                       SUM(n_animals)::float AS animal_days, MAX(date) AS max_date
                FROM {self.mi}.day_cell
                WHERE date >= CAST(:start AS date) AND date < CAST(:origin AS date)
                GROUP BY 1, 2, 3, 4, 5""",
            start=start, origin=origin,
        )

    def transitions(self, start: date, month_end: date) -> pd.DataFrame:
        return self._q(
            f"""SELECT month, from_state, to_state, SUM(n_moved)::float AS n_moved,
                       MAX((month + interval '1 month' - interval '1 day')::date) AS max_date
                FROM {self.core}.state_transition_month
                WHERE month >= CAST(:start AS date) AND month < CAST(:month_end AS date)
                GROUP BY 1, 2, 3""",
            start=start, month_end=month_end,
        )

    def panel_months(self, start: date, origin: date) -> pd.DataFrame:
        sums = ", ".join(f"SUM({c})::float AS {c}" for c in EVENT_COLUMNS)
        return self._q(
            f"""SELECT month, COUNT(*)::float AS days, {sums}, MAX(date) AS max_date
                FROM {self.mi}.day_panel
                WHERE date >= CAST(:start AS date) AND date < CAST(:origin AS date)
                GROUP BY month""",
            start=start, origin=origin,
        )

    def cow_open(self, start: date, known_until: date) -> pd.DataFrame:
        return self._q(
            f"""WITH {_lac_cte(self.core)}, {_BANDS},
                iv AS (
                    SELECT *, GREATEST(calving_date, CAST(:start AS date)) AS s,
                           LEAST(milk_end, COALESCE(conc, 'infinity'::date),
                                 CAST(:known_until AS date)) AS e
                    FROM lac
                    WHERE calving_date < CAST(:known_until AS date)
                )
                SELECT iv.parity_group, b.dim_band,
                       SUM(GREATEST(0, LEAST(iv.e, iv.calving_date + b.hi + 1)
                                       - GREATEST(iv.s, iv.calving_date + b.lo)))::float AS open_days,
                       SUM(CASE WHEN iv.conc >= CAST(:start AS date) AND iv.conc < iv.milk_end
                                 AND (iv.conc - iv.calving_date) BETWEEN b.lo AND b.hi
                                THEN 1 ELSE 0 END)::float AS conceptions,
                       SUM(CASE WHEN iv.dry_off_date >= CAST(:start AS date)
                                 AND iv.dry_off_date < CAST(:known_until AS date)
                                 AND (iv.conc IS NULL OR iv.conc >= iv.dry_off_date)
                                 AND (iv.dry_off_date - iv.calving_date) BETWEEN b.lo AND b.hi
                                THEN 1 ELSE 0 END)::float AS open_dry_offs,
                       MAX(GREATEST(iv.calving_date, iv.conc,
                           CASE WHEN iv.dry_off_date < CAST(:known_until AS date)
                                THEN iv.dry_off_date END)) AS max_date
                FROM iv CROSS JOIN bands b
                GROUP BY 1, 2""",
            start=start, known_until=known_until,
        )

    def preg_milking_days(self, start: date, known_until: date, origin: date) -> pd.DataFrame:
        return self._q(
            f"""WITH {_lac_cte(self.core)}
                SELECT SUM(GREATEST(0, LEAST(milk_end, CAST(:origin AS date))
                                       - GREATEST(conc, CAST(:start AS date))))::float
                           AS preg_milking_days,
                       MAX(conc) AS max_date
                FROM lac WHERE conc IS NOT NULL AND conc < milk_end""",
            start=start, known_until=known_until, origin=origin,
        )

    def dryoff_gest(self, start: date, known_until: date, origin: date) -> pd.DataFrame:
        return self._q(
            f"""SELECT (l.dry_off_date - l.conception_date) AS gest, COUNT(*)::float AS n,
                       MAX(l.dry_off_date) AS max_date
                FROM {self.core}.lactation l
                WHERE l.dry_off_date >= CAST(:start AS date)
                  AND l.dry_off_date < CAST(:origin AS date)
                  AND l.conception_date > l.calving_date
                  AND l.conception_date < l.dry_off_date
                  AND l.conception_date < CAST(:known_until AS date)
                  AND COALESCE(l.is_bad_date, false) = false
                GROUP BY 1""",
            start=start, known_until=known_until, origin=origin,
        )

    def gestation(self, start: date, origin: date) -> pd.DataFrame:
        return self._q(
            f"""SELECT gestation_d AS gest, COUNT(*)::float AS n, MAX(birth_date) AS max_date
                FROM (SELECT DISTINCT dam_key, birth_date, gestation_d
                      FROM {self.core}.calf
                      WHERE birth_date >= CAST(:start AS date)
                        AND birth_date < CAST(:origin AS date)
                        AND gestation_d BETWEEN 200 AND 329) c
                GROUP BY 1""",
            start=start, origin=origin,
        )

    # calf sex split (only used as male/female shares of measured totals) --
    def young_days(self, start: date, origin: date) -> pd.DataFrame:
        """Animal-days aged under one year in [start, origin), by sex."""
        return self._q(
            f"""SELECT a.sex,
                       SUM(GREATEST(0,
                           LEAST(COALESCE(a.exit_date, 'infinity'::date), a.birth_date + 365,
                                 CAST(:origin AS date))
                           - GREATEST(a.birth_date, CAST(:start AS date))))::float AS days,
                       MAX(a.birth_date) AS max_date
                FROM {self.core}.animal a
                WHERE a.sex IN ('female', 'male')
                  AND a.birth_date < CAST(:origin AS date)
                  AND a.birth_date + 365 > CAST(:start AS date)
                  AND COALESCE(a.is_placeholder, false) = false
                GROUP BY a.sex""",
            start=start, origin=origin,
        )

    def young_exits(self, start: date, origin: date) -> pd.DataFrame:
        """Exits before one year of age in [start, origin), by sex and exit type."""
        return self._q(
            f"""SELECT a.sex, a.exit_type, COUNT(*)::float AS exits, MAX(a.exit_date) AS max_date
                FROM {self.core}.animal a
                WHERE a.sex IN ('female', 'male')
                  AND a.exit_date >= CAST(:start AS date)
                  AND a.exit_date < CAST(:origin AS date)
                  AND a.exit_date < a.birth_date + 365
                  AND COALESCE(a.is_placeholder, false) = false
                GROUP BY 1, 2""",
            start=start, origin=origin,
        )

    def births_by_sex(self, start: date, origin: date) -> pd.DataFrame:
        """Live-born calves in [start, origin), by sex."""
        return self._q(
            f"""SELECT sex, COUNT(*)::float AS n, MAX(birth_date) AS max_date
                FROM {self.core}.calf
                WHERE sex IN ('female', 'male')
                  AND birth_date >= CAST(:start AS date)
                  AND birth_date < CAST(:origin AS date)
                  AND NOT COALESCE(born_dead, false)
                GROUP BY sex""",
            start=start, origin=origin,
        )

    def calf_sex_on(self, asof: date) -> pd.DataFrame:
        """Animals under one year old present on ``asof``, by sex and generation."""
        return self._q(
            f"""SELECT a.sex, {_GENERATION} AS generation_group, COUNT(*)::float AS n,
                       MAX(a.birth_date) AS max_date
                FROM {self.core}.animal a
                WHERE a.sex IN ('female', 'male')
                  AND a.birth_date <= CAST(:asof AS date)
                  AND a.birth_date > CAST(:asof AS date) - 365
                  AND COALESCE(a.exit_date, 'infinity'::date) > CAST(:asof AS date)
                  AND COALESCE(a.is_placeholder, false) = false
                GROUP BY 1, 2""",
            asof=asof,
        )

    # actuals for scoring (herd-level daily panel, never fed to the model) --
    def panel_daily(self, start: date, end: date) -> pd.DataFrame:
        cols = ", ".join((*STOCK_COLUMNS, *EVENT_COLUMNS))
        frame = self._q(
            f"""SELECT date, {cols} FROM {self.mi}.day_panel
                WHERE date >= CAST(:start AS date) AND date < CAST(:end AS date)
                ORDER BY date""",
            start=start, end=end,
        )
        frame["date"] = pd.to_datetime(frame["date"]).dt.date
        return frame
