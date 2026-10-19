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
# Milking cells for the synthetic milk tables: parity, DIM range, generation, cows
MILK_CELLS = (("1", (0, 60), "0", 10.0), ("1", (61, 150), "1", 12.0),
              ("2", (151, 300), "1", 8.0), ("3+", (310, 400), "0", 4.0))
TRUE_WOOD = (12.0, 0.25, 0.004)
K_TRUE = {"shipment": 0.9, "delpro": 1.05}


def wood_true(dim):
    d = np.maximum(np.asarray(dim, dtype=float), 1.0)
    a, b, c = TRUE_WOOD
    return a * d ** b * np.exp(-c * d)


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
    s.calf[0, 0], s.calf[0, 1] = 14.0, 6.0  # female calves, generations 0 and 1
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
        self.cutoff, self.future_scale = cutoff, future_scale
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
                   "dry_open": ("dry_pregnant", 1 / 100),
                   "heifer_pregnant": ("milking", 1 / 280)}.get(r.state)
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

    def cow_open(self, start, known_until, origin=None):
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

    def young_days(self, start, origin):
        self.calls.append(("young_days", start, origin))
        out = pd.DataFrame({"sex": ["female", "male"], "days": [6000.0, 2000.0],
                            "max_date": [origin - timedelta(days=1)] * 2})
        return self._leaky("young_days", out, origin)

    def young_exits(self, start, origin):
        self.calls.append(("young_exits", start, origin))
        out = pd.DataFrame({"sex": ["female", "male", "male"],
                            "exit_type": ["died", "died", "sold"], "exits": [2.0, 8.0, 6.0],
                            "max_date": [origin - timedelta(days=1)] * 3})
        return self._leaky("young_exits", out, origin)

    def daily_moves(self, start, end):
        self.calls.append(("daily_moves", start, end))
        p = self.panel[(self.panel["date"] >= start) & (self.panel["date"] < end)]
        rows = []
        for r in p.itertuples(index=False):
            for frm, to, n in (("heifers", "milking", r.calvings * 0.3), ("dry", "milking", r.calvings * 0.7),
                               ("milking", "dry", r.dry_offs), ("born", "calves", r.births),
                               ("milking", "dead", r.deaths), ("dry", "culled", r.culls), ("dry", "sold", r.sales),
                               ("calves", "heifers", 0.1)):
                if n > 0:
                    rows.append((r.date, frm, to, float(n), r.date))
        out = pd.DataFrame(rows, columns=["date", "from_group", "to_group", "n", "max_date"])
        return self._leaky("daily_moves", out, end)

    def births_by_sex(self, start, origin):
        self.calls.append(("births_by_sex", start, origin))
        out = pd.DataFrame({"sex": ["female", "male"], "n": [52.0, 48.0],
                            "max_date": [origin - timedelta(days=1)] * 2})
        return self._leaky("births_by_sex", out, origin)

    def calf_sex_on(self, asof):
        self.calls.append(("calf_sex_on", asof))
        out = pd.DataFrame({"sex": ["female", "male", "female"],
                            "generation_group": ["0", "0", "1"], "n": [9.0, 3.0, 6.0],
                            "max_date": [asof] * 3})
        return self._leaky("calf_sex_on", out, asof + timedelta(days=1))

    # ---- milk (SYNTHETIC): known curve and k so tests can check recovery ----------
    def _milk_tables(self):
        if hasattr(self, "_cowdays"):
            return
        months = []
        d = SYNTHETIC_START
        while d < SYNTHETIC_END:
            months.append(d)
            d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
        rows = []
        for i, m in enumerate(months):
            ndays = ((m.replace(day=28) + timedelta(days=4)).replace(day=1) - m).days
            for par, (lo, hi), gen, n in MILK_CELLS:
                bins = list(range(lo, hi + 1, 10))
                for j, b in enumerate(bins):
                    w = 1 + 0.6 * sin(2 * pi * i / 12 + j)  # DIM mix moves through the year
                    rows.append((m, par, gen, b, -1, n * ndays * w / len(bins)))
        cd = pd.DataFrame(rows, columns=["month", "parity_group", "generation_group", "dim_bin",
                                         "preg_band", "cow_days"])
        cd["max_date"] = [(m.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
                          for m in cd["month"]]
        self._cowdays = cd
        lit = (cd["cow_days"] * wood_true(cd["dim_bin"] + 5)).groupby(cd["month"]).sum()
        days = []
        for m in months:
            nd = ((m.replace(day=28) + timedelta(days=4)).replace(day=1) - m).days
            for k in range(nd):
                day = m + timedelta(days=k)
                src = "shipment" if day < date(2020, 8, 1) else "delpro"
                ok = not (date(2018, 5, 1) <= day < date(2018, 6, 1))  # a synthetic gap month
                f = self.future_scale if self.cutoff and day >= self.cutoff else 1.0
                days.append((day, src, f * K_TRUE[src] * lit[m] / nd, ok, None, not ok))
        self._target = pd.DataFrame(days, columns=["date", "target_source", "target_litres",
                                                   "is_scoreable", "identified_share", "data_gap"])

    def cow_curve_stats(self, start, end):
        self.calls.append(("cow_curve_stats", start, end))
        cols = ["parity_group", "generation_group", "dim", "preg_band", "n", "sum_yield", "max_date"]
        if end <= date(2020, 8, 1):
            return pd.DataFrame(columns=cols)
        rows = []
        for par, scale in (("1", 1.0), ("2", 1.1), ("3+", 1.15)):
            for gen in ("0", "1"):
                for dim in range(1, 401):
                    band = -1 if dim < 120 else 0 if dim < 250 else 150 if dim < 330 else 200
                    m = {150: 0.95, 200: 0.9}.get(band, 1.0)
                    rows.append((par, gen, dim, band, 20.0, 20.0 * float(wood_true(dim)) * scale * m,
                                 end - timedelta(days=1)))
        return self._leaky("cow_curve_stats", pd.DataFrame(rows, columns=cols), end)

    def milking_cowdays(self, start, end):
        self.calls.append(("milking_cowdays", start, end))
        self._milk_tables()
        cd = self._cowdays
        return cd[(cd["month"] >= start) & (cd["month"] < end)].reset_index(drop=True)

    def target_daily(self, start, end):
        self.calls.append(("target_daily", start, end))
        self._milk_tables()
        t = self._target
        return t[(t["date"] >= start) & (t["date"] < end)].reset_index(drop=True)

    def health_months(self, start, end):
        self.calls.append(("health_months", start, end))
        p = self.panel[(self.panel["date"] >= start) & (self.panel["date"] < end)]
        out = p.groupby("month", as_index=False).agg(max_date=("date", "max"))
        out["mastitis_episodes"] = [3.0 if m < date(2019, 1, 1) else 0.5 for m in out["month"]]
        out["udder_teat_episodes"] = 1.0
        return self._leaky("health_months", out, end)

    def data_coverage(self, end):
        years = range(2016, end.year + 1)
        return pd.DataFrame({"year": list(years), "reliable_cow_days": [0] * 4 + [1000] * (len(years) - 4),
                             "milk_days_scoreable_pct": 0.95, "weather_complete_pct": 0.9,
                             "health_records": 10, "max_date": end - timedelta(days=1)})

    def generation_fertility(self):
        return pd.DataFrame({"generation_group": ["0", "1"], "calving_period": ["2020-2022"] * 2,
                             "lactations": [100, 80], "conceptions": [70, 50],
                             "services_per_conception": [3.5, 4.2], "pct_aborted": [3.0, 4.0]})

    def panel_daily(self, start, end):
        self.calls.append(("panel_daily", start, end))
        p = self.panel[(self.panel["date"] >= start) & (self.panel["date"] < end)]
        return p.drop(columns="month").reset_index(drop=True)
