"""SYNTHETIC test fixtures: a small fictional herd. Not Farm X data.

``FakeHerdSource`` implements the ``HerdSource`` protocol from in-memory synthetic
tables, so tests never open a database connection. It records every call and can
inject a future-dated row into one query to test the leakage guard.
"""
from __future__ import annotations

from datetime import date, timedelta
from math import sin, pi

import numpy as np
import pandas as pd

from components.predictive_farm_intelligence.pfoi.categories import (
    COW_PARITIES, DIM_BANDS, EXIT_TYPES, STATE_TO_STOCK, STATES,
)
from components.predictive_farm_intelligence.pfoi.herd_engine import (
    N_GEST, OriginState, RateSet,
)

SYNTHETIC_START = date(2015, 8, 1)
SYNTHETIC_END = date(2024, 3, 1)

# (state, parity_group, dim_band, generation_group, n) for a fictional 90-animal herd
BASE_CELLS = (
    ("calf", "0", "na", "0", 14.0),
    ("calf", "0", "na", "1", 6.0),
    ("heifer_open", "0", "na", "0", 15.0),
    ("heifer_pregnant", "0", "na", "1", 10.0),
    ("milking", "1", "0-60", "0", 10.0),
    ("milking", "1", "61-150", "1", 12.0),
    ("milking", "2", "151-305", "1", 8.0),
    ("milking", "3+", "305+", "0", 4.0),
    ("milking", "2", "unknown", "2", 2.0),
    ("dry_open", "2", "na", "0", 3.0),
    ("dry_pregnant", "2", "na", "1", 7.0),
    ("bull", "unknown", "na", "unknown", 2.0),
    ("unknown", "unknown", "na", "unknown", 1.0),
)
DAILY_EVENTS = {
    "calvings": 0.12, "dry_offs": 0.10, "ais": 0.30, "real_abortions": 0.01,
    "deaths": 0.01, "culls": 0.02, "sales": 0.03, "births": 0.06, "external_entries": 0.005,
}


def synthetic_rates(**overrides) -> RateSet:
    calve = np.zeros(N_GEST)
    calve[275:290] = 0.2
    dry = np.zeros(N_GEST)
    dry[215:230] = 0.15
    kwargs = dict(
        exit={s: {k: 0.0002 for k in EXIT_TYPES} for s in STATES},
        calf_to_heifer=1 / 365,
        conc_heifer=1 / 120,
        conc_dry=1 / 150,
        conc_cow=np.tile([0.0, 0.01, 0.006, 0.002], (len(COW_PARITIES), 1)),
        dry_open_cow=np.array([0.0, 0.0005, 0.002, 0.01]),
        dry_preg_by_gest=dry,
        calve_by_gest=calve,
        abortion=0.0003,
        births_per_calving=0.5,
        ai_open=0.02,
        entry_per_day=0.01,
        entry_shares={"heifer_open": 0.7, "milking": 0.3},
    )
    kwargs.update(overrides)
    return RateSet(**kwargs)


def synthetic_state(origin: date = date(2020, 1, 1)) -> OriginState:
    s = OriginState(origin=origin)
    s.calf[0], s.calf[1] = 14.0, 6.0
    s.heifer_open[0] = 15.0
    s.heifer_preg[1, 200] = 10.0
    s.milk_open[0, 0, 30] = 10.0
    s.milk_open[0, 1, 120] = 12.0
    s.milk_preg[1, 1, 9, 50] = 8.0
    s.milk_open[2, 0, 330] = 4.0
    s.dry_open[1, 0] = 3.0
    s.dry_preg[1, 1, 250] = 7.0
    s.bull, s.unknown = 2.0, 1.0
    return s


def _seasonal(d: date) -> float:
    return 1.0 + 0.1 * sin(2 * pi * d.timetuple().tm_yday / 365.0)


class FakeHerdSource:
    """Synthetic in-memory HerdSource. ``future_scale`` multiplies every daily row dated
    on/after ``cutoff``; ``leak`` names a method that returns a row dated at its bound."""

    def __init__(self, leak: str | None = None, cutoff: date | None = None,
                 future_scale: float = 1.0):
        self.leak = leak
        self.calls: list[tuple] = []
        days = pd.date_range(SYNTHETIC_START, SYNTHETIC_END - timedelta(days=1)).date
        rows = []
        for d in days:
            f = _seasonal(d) * (future_scale if cutoff and d >= cutoff else 1.0)
            for state, par, band, gen, n in BASE_CELLS:
                rows.append((d, state, par, band, gen, n * f))
        self.cells = pd.DataFrame(
            rows, columns=["date", "state", "parity_group", "dim_band", "generation_group", "n_animals"]
        )
        self.cells["month"] = [d.replace(day=1) for d in self.cells["date"]]
        stock = (self.cells.groupby(["date", "state"])["n_animals"].sum().unstack(fill_value=0.0)
                 .rename(columns=STATE_TO_STOCK))
        stock["n_herd"] = stock.sum(axis=1)
        panel = stock.reset_index()
        for col, rate in DAILY_EVENTS.items():
            panel[col] = [rate * _seasonal(d) * (future_scale if cutoff and d >= cutoff else 1.0)
                          for d in panel["date"]]
        panel["exits"] = panel["deaths"] + panel["culls"] + panel["sales"]
        panel["month"] = [d.replace(day=1) for d in panel["date"]]
        self.panel = panel

    def _leaky(self, name: str, frame: pd.DataFrame, bound: date) -> pd.DataFrame:
        if self.leak == name:
            extra = frame.head(1).copy()
            extra["max_date"] = bound
            frame = pd.concat([frame, extra], ignore_index=True)
        return frame

    # starting herd
    def cells_on(self, asof):
        self.calls.append(("cells_on", asof))
        c = self.cells[self.cells["date"] == asof]
        out = (c.groupby(["state", "parity_group", "dim_band", "generation_group"], as_index=False)
               ["n_animals"].sum().rename(columns={"n_animals": "n"}))
        out["max_date"] = asof
        return self._leaky("cells_on", out, asof + timedelta(days=1))

    def milking_clock(self, asof, known_until):
        self.calls.append(("milking_clock", asof, known_until))
        out = pd.DataFrame({
            "parity_group": ["1", "1", "1", "2", "3+"],
            "generation_group": ["0", "1", "1", "1", "0"],
            "dim": [20, 100, 140, 200, 340],
            "gest": [np.nan, np.nan, 60.0, 110.0, np.nan],
            "recent_ai_gest": [np.nan, 20.0, np.nan, np.nan, np.nan],
            "n": [3.0, 4.0, 2.0, 5.0, 1.0],
        })
        out["max_date"] = known_until - timedelta(days=1)
        return self._leaky("milking_clock", out, asof + timedelta(days=1))

    def dry_clock(self, asof, known_until):
        self.calls.append(("dry_clock", asof, known_until))
        out = pd.DataFrame({"parity_group": ["2", "2"], "generation_group": ["1", "0"],
                            "gest": [240.0, np.nan], "n": [3.0, 1.0]})
        out["max_date"] = known_until - timedelta(days=1)
        return self._leaky("dry_clock", out, asof + timedelta(days=1))

    def heifer_clock(self, asof, known_until, lag_days):
        self.calls.append(("heifer_clock", asof, known_until, lag_days))
        out = pd.DataFrame({"generation_group": ["1", "1"], "gest": [100, 180], "n": [2.0, 3.0]})
        out["max_date"] = known_until - timedelta(days=1)
        return self._leaky("heifer_clock", out, known_until)

    # rate inputs
    def exposure(self, start, origin):
        self.calls.append(("exposure", start, origin))
        c = self.cells[(self.cells["date"] >= start) & (self.cells["date"] < origin)]
        out = (c.groupby(["month", "state", "parity_group", "dim_band", "generation_group"],
                         as_index=False)
               .agg(animal_days=("n_animals", "sum"), max_date=("date", "max")))
        return self._leaky("exposure", out, origin)

    def transitions(self, start, month_end):
        self.calls.append(("transitions", start, month_end))
        c = self.cells[(self.cells["month"] >= start) & (self.cells["month"] < month_end)]
        days = c.groupby(["month", "state"])["n_animals"].sum().reset_index()
        rows = []
        for r in days.itertuples(index=False):
            nxt = {"calf": ("heifer_open", 1 / 365), "heifer_open": ("heifer_pregnant", 1 / 120),
                   "dry_open": ("dry_pregnant", 1 / 100)}.get(r.state)
            if nxt:
                rows.append((r.month, r.state, nxt[0], r.n_animals * nxt[1]))
            for to_state, rate in (("dead", 0.0001), ("culled", 0.0002), ("sold", 0.0003)):
                rows.append((r.month, r.state, to_state, r.n_animals * rate))
        out = pd.DataFrame(rows, columns=["month", "from_state", "to_state", "n_moved"])
        out["max_date"] = [(m.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
                           for m in out["month"]]
        return self._leaky("transitions", out, month_end)

    def panel_months(self, start, origin):
        self.calls.append(("panel_months", start, origin))
        p = self.panel[(self.panel["date"] >= start) & (self.panel["date"] < origin)]
        agg = {c: (c, "sum") for c in DAILY_EVENTS}
        agg["exits"] = ("exits", "sum")
        out = p.groupby("month", as_index=False).agg(days=("date", "count"),
                                                    max_date=("date", "max"), **agg)
        return self._leaky("panel_months", out, origin)

    def cow_open(self, start, known_until):
        self.calls.append(("cow_open", start, known_until))
        rows = []
        for p in ("1", "2", "3+"):
            for b, (days, conc, dry) in zip(DIM_BANDS, ((600, 0, 0), (900, 9, 1), (1200, 6, 3), (300, 1, 4))):
                rows.append((p, b, float(days), float(conc), float(dry)))
        out = pd.DataFrame(rows, columns=["parity_group", "dim_band", "open_days", "conceptions",
                                          "open_dry_offs"])
        out["max_date"] = known_until - timedelta(days=1)
        return self._leaky("cow_open", out, known_until)

    def preg_milking_days(self, start, known_until, origin):
        self.calls.append(("preg_milking_days", start, known_until, origin))
        out = pd.DataFrame({"preg_milking_days": [2500.0], "max_date": [known_until - timedelta(days=1)]})
        return self._leaky("preg_milking_days", out, origin)

    def dryoff_gest(self, start, known_until, origin):
        self.calls.append(("dryoff_gest", start, known_until, origin))
        out = pd.DataFrame({"gest": np.arange(210, 231), "n": np.full(21, 2.0)})
        out["max_date"] = origin - timedelta(days=1)
        return self._leaky("dryoff_gest", out, origin)

    def gestation(self, start, origin):
        self.calls.append(("gestation", start, origin))
        out = pd.DataFrame({"gest": np.arange(275, 288), "n": np.full(13, 3.0)})
        out["max_date"] = origin - timedelta(days=1)
        return self._leaky("gestation", out, origin)

    def panel_daily(self, start, end):
        self.calls.append(("panel_daily", start, end))
        p = self.panel[(self.panel["date"] >= start) & (self.panel["date"] < end)]
        return p.drop(columns="month").reset_index(drop=True)
