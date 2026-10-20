"""Daily herd engine: projects herd cells forward from an origin.

The herd is held as expected (fractional) counts in compartments keyed by state,
parity group and generation group, with two internal clocks:

* days in milk (DIM) for open milking cows;
* days since conception (gestation day) for pregnant animals. Pregnant milking
  cows also keep their DIM at conception in 10-day bins, so DIM can be reported.

Each simulated day runs, in this order:

1. ageing: every clock moves on one day;
2. exits (death, cull, sale) by state;
3. real abortion: pregnant -> open; plus extra pregnancy losses for heifers and dry
   cows measured from the transition table (not counted as abortions);
4. calving by gestation day: dam -> milking, parity + 1, DIM 0; retained
   calves enter "calf" (split female/male by the birth sex ratio; calves that die
   within their first month are counted as births and deaths only) with
   generation = dam generation + 1 (capped at 3+);
5. dry-off: open cows by DIM band, pregnant cows by gestation day;
6. conception (heifer, milking cow by parity x DIM band, dry cow), female calf ->
   heifer, male calf -> bull,
   and inseminations counted as events;
7. external entries.

Every flow takes a fraction (at most 1) of what is left, so counts never go negative,
and stock(t) = stock(t-1) - exits + births + entries holds exactly.
Bulls and unknown-state animals are only reduced by exits.

The engine never touches data or dates beyond what it is given: it is a pure function
of an ``OriginState`` and a ``RateSet``.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .categories import (
    CHILD_GENERATION,
    SEXES,
    COW_PARITIES,
    DIM_BAND_BOUNDS,
    DIM_BANDS,
    EXIT_TYPES,
    FIRST_PARITY,
    GENERATIONS,
    NA_BAND,
    NEXT_PARITY,
    STATE_TO_STOCK,
    STATES,
)

N_PAR = len(COW_PARITIES)
N_GEN = len(GENERATIONS)
N_SEX = len(SEXES)  # 0 = female, 1 = male
N_DIM = 1000  # last index absorbs DIM >= 999
CB_WIDTH = 10  # bin width of DIM at conception for pregnant milking cows
N_CB = N_DIM // CB_WIDTH
N_GEST = 330  # gestation days 0..329; calving hazard is 1 on the last day
N_BAND = len(DIM_BANDS)


def _band_of_dim() -> np.ndarray:
    out = np.zeros(N_DIM, dtype=int)
    for i, (lo, hi) in enumerate(DIM_BAND_BOUNDS):
        out[lo : (N_DIM if hi is None else hi + 1)] = i
    return out


BAND_OF_DIM = _band_of_dim()
# Current DIM of a pregnant milking cow in conception bin c at gestation day t.
_DIM_OF_PREG = np.minimum(
    (np.arange(N_CB)[:, None] * CB_WIDTH + CB_WIDTH // 2) + np.arange(N_GEST)[None, :],
    N_DIM - 1,
)
_DIM_OF_PREG_FLAT = _DIM_OF_PREG.ravel()
_BAND_MASK_PREG = np.eye(N_BAND)[BAND_OF_DIM[_DIM_OF_PREG_FLAT]]  # (N_CB*N_GEST, N_BAND)
_BAND_MASK_OPEN = np.eye(N_BAND)[BAND_OF_DIM]  # (N_DIM, N_BAND)


# Milking-cow mix for attribution: 10-day DIM bins x pregnancy band
# (band index 0 = open, 1 = < 150 days pregnant, 2 = 150-199, 3 = 200+).
PREG_BAND_VALUES = (-1, 0, 150, 200)
N_DIM_BIN = N_DIM // 10
_PREG_DIMBIN = np.minimum(_DIM_OF_PREG_FLAT // 10, N_DIM_BIN - 1)
_PREG_BAND = 1 + np.digitize(np.tile(np.arange(N_GEST), N_CB), [150, 200])
_PREG_MIX_INDEX = _PREG_DIMBIN * 4 + _PREG_BAND


def _flow(ev: dict, state: str, name: str, value: float) -> None:
    """Record a signed flow into or out of ``state`` (keys ``flow|state|name``)."""
    key = f"flow|{state}|{name}"
    ev[key] = ev.get(key, 0.0) + float(value)


@dataclass
class OriginState:
    """Herd at the end of the day before the origin, as expected counts."""

    origin: date
    calf: np.ndarray = field(default_factory=lambda: np.zeros((N_SEX, N_GEN)))
    heifer_open: np.ndarray = field(default_factory=lambda: np.zeros(N_GEN))
    heifer_preg: np.ndarray = field(default_factory=lambda: np.zeros((N_GEN, N_GEST)))
    milk_open: np.ndarray = field(default_factory=lambda: np.zeros((N_PAR, N_GEN, N_DIM)))
    milk_preg: np.ndarray = field(
        default_factory=lambda: np.zeros((N_PAR, N_GEN, N_CB, N_GEST))
    )
    dry_open: np.ndarray = field(default_factory=lambda: np.zeros((N_PAR, N_GEN)))
    dry_preg: np.ndarray = field(default_factory=lambda: np.zeros((N_PAR, N_GEN, N_GEST)))
    bull: float = 0.0
    unknown: float = 0.0

    def copy(self) -> "OriginState":
        return replace(
            self,
            **{
                name: getattr(self, name).copy()
                for name in (
                    "calf",
                    "heifer_open",
                    "heifer_preg",
                    "milk_open",
                    "milk_preg",
                    "dry_open",
                    "dry_preg",
                )
            },
        )

    def state_totals(self) -> dict[str, float]:
        return {
            "calf": float(self.calf.sum()),
            "heifer_open": float(self.heifer_open.sum()),
            "heifer_pregnant": float(self.heifer_preg.sum()),
            "milking": float(self.milk_open.sum() + self.milk_preg.sum()),
            "dry_open": float(self.dry_open.sum()),
            "dry_pregnant": float(self.dry_preg.sum()),
            "bull": float(self.bull),
            "unknown": float(self.unknown),
        }

    def total(self) -> float:
        return float(sum(self.state_totals().values()))

    def cells(self) -> pd.DataFrame:
        """Herd as day_cell-style rows (state, parity_group, dim_band, generation_group, n)."""
        rows: list[tuple[str, str, str, str, float]] = []
        for g, gen in enumerate(GENERATIONS):
            rows.append(("calf", "0", NA_BAND, gen, self.calf[:, g].sum()))
            rows.append(("heifer_open", "0", NA_BAND, gen, self.heifer_open[g]))
            rows.append(("heifer_pregnant", "0", NA_BAND, gen, self.heifer_preg[g].sum()))
        open_bands = self.milk_open @ _BAND_MASK_OPEN
        preg_bands = self.milk_preg.reshape(N_PAR * N_GEN, -1) @ _BAND_MASK_PREG
        milk_bands = open_bands + preg_bands.reshape(N_PAR, N_GEN, N_BAND)
        for p, par in enumerate(COW_PARITIES):
            for g, gen in enumerate(GENERATIONS):
                for b, band in enumerate(DIM_BANDS):
                    rows.append(("milking", par, band, gen, milk_bands[p, g, b]))
                rows.append(("dry_open", par, NA_BAND, gen, self.dry_open[p, g]))
                rows.append(("dry_pregnant", par, NA_BAND, gen, self.dry_preg[p, g].sum()))
        rows.append(("bull", "unknown", NA_BAND, "unknown", self.bull))
        rows.append(("unknown", "unknown", NA_BAND, "unknown", self.unknown))
        frame = pd.DataFrame(
            rows, columns=["state", "parity_group", "dim_band", "generation_group", "n"]
        )
        return frame[frame["n"] > 0].reset_index(drop=True)


@dataclass
class RateSet:
    """Daily hazards (probability per animal-day) and distributions for the engine."""

    exit: dict[str, dict[str, float]]  # state -> exit type (deaths/culls/sales) -> hazard
    calf_to_heifer: float
    conc_heifer: float
    conc_dry: float
    conc_cow: np.ndarray  # (N_PAR, N_BAND) by parity group x DIM band
    dry_open_cow: np.ndarray  # (N_BAND,) dry-off hazard of open milking cows by DIM band
    dry_preg_by_gest: np.ndarray  # (N_GEST,) dry-off hazard of pregnant milking cows
    calve_by_gest: np.ndarray  # (N_GEST,) calving hazard by gestation day
    abortion: float
    births_per_calving: float
    ai_open: float
    # Calf sex split. Defaults reproduce a single calf group (all treated as female).
    female_share: float = 1.0  # share of calves born that are female
    calf_to_bull: float = 0.0  # daily hazard, male calves only
    calf_exit_by_sex: dict[str, dict[str, float]] | None = None  # sex -> exit type -> hazard
    # calves that die before they are counted in the herd (born and dead within a month)
    early_deaths_per_calving: float = 0.0
    heifer_loss: float = 0.0  # extra pregnant -> open hazard for heifers (not counted as abortion)
    dry_loss: float = 0.0  # same for dry cows
    entry_per_day: float = 0.0
    entry_shares: dict[str, float] = field(default_factory=lambda: {"heifer_open": 1.0})
    entry_dim: int = 100
    entry_gestation: int = 150
    notes: tuple[str, ...] = ()
    # M7: multiplier of the cow conception rate per day in milk (N_DIM,); None = flat bands
    conc_dim_shape: np.ndarray | None = None
    # exit fix: daily exit hazard of milking cows by parity x DIM band x pregnancy status
    # (N_PAR, N_BAND, 2); split into exit types by ``exit["milking"]``. None = one rate.
    milk_exit_cell: np.ndarray | None = None

    def __post_init__(self) -> None:
        self.conc_cow = np.clip(np.asarray(self.conc_cow, dtype=float), 0.0, 1.0)
        self.dry_open_cow = np.clip(np.asarray(self.dry_open_cow, dtype=float), 0.0, 1.0)
        self.dry_preg_by_gest = np.clip(np.asarray(self.dry_preg_by_gest, float), 0.0, 1.0)
        calve = np.clip(np.asarray(self.calve_by_gest, dtype=float), 0.0, 1.0)
        calve[-1] = 1.0
        self.calve_by_gest = calve
        if self.conc_cow.shape != (N_PAR, N_BAND):
            raise ValueError("conc_cow must have shape (parity groups, DIM bands)")
        for state in STATES:
            self.exit.setdefault(state, {k: 0.0 for k in EXIT_TYPES})
        total = sum(self.entry_shares.values())
        if self.entry_per_day > 0 and total <= 0:
            raise ValueError("entry_shares must be positive when entries are projected")
        if total > 0:
            self.entry_shares = {k: v / total for k, v in self.entry_shares.items()}


@dataclass
class Projection:
    origin: date
    daily: pd.DataFrame  # one row per projected day: stocks and events
    cells: pd.DataFrame | None  # optional daily day_cell-style rows
    final_state: OriginState
    milk_mix: np.ndarray | None = None  # optional (days, N_PAR, N_DIM_BIN, 4) milking mix


def _shift(arr: np.ndarray) -> np.ndarray:
    """Move a clock (last axis) on by one day; the last bucket absorbs."""
    out = np.zeros_like(arr)
    out[..., 1:] = arr[..., :-1]
    out[..., -1] += arr[..., -1]
    return out


def _preg_to_open_dim(flow: np.ndarray) -> np.ndarray:
    """Scatter flows out of milk_preg (P, G, CB, GEST) onto milk_open DIM (P, G, DIM)."""
    flat = flow.reshape(N_PAR * N_GEN, -1)
    out = np.empty((N_PAR * N_GEN, N_DIM))
    for i in range(flat.shape[0]):
        out[i] = np.bincount(_DIM_OF_PREG_FLAT, weights=flat[i], minlength=N_DIM)
    return out.reshape(N_PAR, N_GEN, N_DIM)


def _exit_fraction(hazards: dict[str, float]) -> tuple[dict[str, float], float]:
    """Cap competing exit hazards so they sum to at most 1."""
    total = sum(max(0.0, h) for h in hazards.values())
    scale = 1.0 / total if total > 1.0 else 1.0
    parts = {k: max(0.0, hazards.get(k, 0.0)) * scale for k in EXIT_TYPES}
    return parts, sum(parts.values())


def _milking_exits_by_cell(s: OriginState, r: RateSet, ev: dict) -> None:
    """Milking-cow exits at the measured hazard of each parity x DIM band x pregnancy cell,
    split into exit types in the proportions of ``r.exit["milking"]``."""
    kinds = {k: max(0.0, r.exit["milking"].get(k, 0.0)) for k in EXIT_TYPES}
    total_kind = sum(kinds.values())
    share = ({k: v / total_kind for k, v in kinds.items()} if total_kind > 0
             else {k: (1.0 if k == "culls" else 0.0) for k in EXIT_TYPES})
    cell = np.clip(r.milk_exit_cell, 0.0, 1.0)
    h_open = cell[:, BAND_OF_DIM, 0]  # (N_PAR, N_DIM)
    h_preg = cell[:, BAND_OF_DIM[_DIM_OF_PREG_FLAT], 1].reshape(N_PAR, 1, N_CB, N_GEST)
    out_open = s.milk_open * h_open[:, None, :]
    out_preg = s.milk_preg * h_preg
    s.milk_open -= out_open
    s.milk_preg -= out_preg
    n = float(out_open.sum() + out_preg.sum())
    for k in EXIT_TYPES:
        ev[k] += n * share[k]
        _flow(ev, "milking", k, -n * share[k])


def step_day(s: OriginState, r: RateSet) -> dict[str, float]:
    """Advance the herd ``s`` (modified in place) by one day; return the day's events."""
    ev = {name: 0.0 for name in (
        "calvings", "dry_offs", "ais", "real_abortions", "deaths", "culls", "sales",
        "exits", "births", "external_entries", "conceptions", "pregnancy_losses",
        "calvings_heifer",
    )}

    # 1. ageing
    s.milk_open = _shift(s.milk_open)
    s.milk_preg = _shift(s.milk_preg)
    s.heifer_preg = _shift(s.heifer_preg)
    s.dry_preg = _shift(s.dry_preg)

    # 2. exits
    for state in STATES:
        if state == "calf" and r.calf_exit_by_sex:
            for i, sex in enumerate(SEXES):
                sparts, stotal = _exit_fraction(r.calf_exit_by_sex[sex])
                ns = float(s.calf[i].sum())
                s.calf[i] *= 1.0 - stotal
                for k, h in sparts.items():
                    ev[k] += ns * h
                    _flow(ev, "calf", k, -ns * h)
            continue
        if state == "milking" and r.milk_exit_cell is not None:
            _milking_exits_by_cell(s, r, ev)
            continue
        parts, total = _exit_fraction(r.exit[state])
        if total <= 0:
            continue
        if state in ("bull", "unknown"):
            n = getattr(s, state)
            setattr(s, state, n * (1.0 - total))
        else:
            arrays = {
                "calf": ("calf",),
                "heifer_open": ("heifer_open",),
                "heifer_pregnant": ("heifer_preg",),
                "milking": ("milk_open", "milk_preg"),
                "dry_open": ("dry_open",),
                "dry_pregnant": ("dry_preg",),
            }[state]
            n = 0.0
            for name in arrays:
                arr = getattr(s, name)
                n += float(arr.sum())
                arr *= 1.0 - total
        for k, h in parts.items():
            ev[k] += n * h
            _flow(ev, state, k, -n * h)
    ev["exits"] = ev["deaths"] + ev["culls"] + ev["sales"]

    # 3. real abortion
    a = r.abortion
    if a > 0:
        flow = s.heifer_preg * a
        s.heifer_preg -= flow
        s.heifer_open += flow.sum(-1)
        ev["real_abortions"] += float(flow.sum())
        _flow(ev, "heifer_pregnant", "abortion", -flow.sum())
        _flow(ev, "heifer_open", "abortion", flow.sum())
        flow = s.dry_preg * a
        s.dry_preg -= flow
        s.dry_open += flow.sum(-1)
        ev["real_abortions"] += float(flow.sum())
        _flow(ev, "dry_pregnant", "abortion", -flow.sum())
        _flow(ev, "dry_open", "abortion", flow.sum())
        flow = s.milk_preg * a
        s.milk_preg -= flow
        s.milk_open += _preg_to_open_dim(flow)
        ev["real_abortions"] += float(flow.sum())
    if r.heifer_loss > 0:
        flow = s.heifer_preg * min(r.heifer_loss, 1.0)
        s.heifer_preg -= flow
        s.heifer_open += flow.sum(-1)
        ev["pregnancy_losses"] += float(flow.sum())
        _flow(ev, "heifer_pregnant", "pregnancy_loss", -flow.sum())
        _flow(ev, "heifer_open", "pregnancy_loss", flow.sum())
    if r.dry_loss > 0:
        flow = s.dry_preg * min(r.dry_loss, 1.0)
        s.dry_preg -= flow
        s.dry_open += flow.sum(-1)
        ev["pregnancy_losses"] += float(flow.sum())
        _flow(ev, "dry_pregnant", "pregnancy_loss", -flow.sum())
        _flow(ev, "dry_open", "pregnancy_loss", flow.sum())

    # 4. calving
    h = r.calve_by_gest
    calved_by_gen = np.zeros(N_GEN)
    flow = s.heifer_preg * h
    s.heifer_preg -= flow
    c = flow.sum(-1)
    calved_by_gen += c
    ev["calvings_heifer"] = float(c.sum())
    _flow(ev, "heifer_pregnant", "calving", -c.sum())
    _flow(ev, "milking", "calving", c.sum())
    fresh = np.zeros((N_PAR, N_GEN))
    fresh[FIRST_PARITY] += c
    flow = s.dry_preg * h
    s.dry_preg -= flow
    c = flow.sum(-1)  # (P, G)
    calved_by_gen += c.sum(0)
    _flow(ev, "dry_pregnant", "calving", -c.sum())
    _flow(ev, "milking", "calving", c.sum())
    for p in range(N_PAR):
        fresh[NEXT_PARITY[p]] += c[p]
    flow = s.milk_preg * h
    s.milk_preg -= flow
    c = flow.sum(axis=(2, 3))
    calved_by_gen += c.sum(0)
    for p in range(N_PAR):
        fresh[NEXT_PARITY[p]] += c[p]
    s.milk_open[:, :, 0] += fresh
    ev["calvings"] = float(calved_by_gen.sum())
    born = calved_by_gen * r.births_per_calving
    early = calved_by_gen * min(r.early_deaths_per_calving, r.births_per_calving)
    kept = born - early
    fs = min(max(r.female_share, 0.0), 1.0)
    for g in range(N_GEN):
        s.calf[0, CHILD_GENERATION[g]] += kept[g] * fs
        s.calf[1, CHILD_GENERATION[g]] += kept[g] * (1.0 - fs)
    ev["births"] = float(born.sum())
    _flow(ev, "calf", "births", kept.sum())
    ev["deaths"] += float(early.sum())
    ev["exits"] += float(early.sum())

    # 5. dry-off
    flow = s.milk_open * r.dry_open_cow[BAND_OF_DIM]
    s.milk_open -= flow
    s.dry_open += flow.sum(-1)
    ev["dry_offs"] += float(flow.sum())
    _flow(ev, "milking", "dry_off", -flow.sum())
    _flow(ev, "dry_open", "dry_off", flow.sum())
    flow = s.milk_preg * r.dry_preg_by_gest
    s.milk_preg -= flow
    s.dry_preg += flow.sum(2)
    ev["dry_offs"] += float(flow.sum())
    _flow(ev, "milking", "dry_off", -flow.sum())
    _flow(ev, "dry_pregnant", "dry_off", flow.sum())

    # 6. inseminations (events only), conception, calf -> heifer
    open_animals = s.heifer_open.sum() + s.milk_open.sum() + s.dry_open.sum()
    ev["ais"] = float(open_animals * r.ai_open)
    flow = s.heifer_open * r.conc_heifer
    s.heifer_open -= flow
    s.heifer_preg[:, 0] += flow
    ev["conceptions"] += float(flow.sum())
    _flow(ev, "heifer_open", "conception", -flow.sum())
    _flow(ev, "heifer_pregnant", "conception", flow.sum())
    conc = r.conc_cow[:, BAND_OF_DIM]
    if r.conc_dim_shape is not None:
        conc = np.clip(conc * r.conc_dim_shape[None, :N_DIM], 0.0, 1.0)
    flow = s.milk_open * conc[:, None, :]
    s.milk_open -= flow
    s.milk_preg[:, :, :, 0] += flow.reshape(N_PAR, N_GEN, N_CB, CB_WIDTH).sum(-1)
    ev["conceptions"] += float(flow.sum())
    flow = s.dry_open * r.conc_dry
    s.dry_open -= flow
    s.dry_preg[:, :, 0] += flow
    ev["conceptions"] += float(flow.sum())
    _flow(ev, "dry_open", "conception", -flow.sum())
    _flow(ev, "dry_pregnant", "conception", flow.sum())
    flow = s.calf[0] * r.calf_to_heifer
    s.calf[0] -= flow
    s.heifer_open += flow
    _flow(ev, "calf", "to_heifer", -flow.sum())
    _flow(ev, "heifer_open", "to_heifer", flow.sum())
    flow = s.calf[1] * r.calf_to_bull
    s.calf[1] -= flow
    s.bull += float(flow.sum())
    _flow(ev, "calf", "to_bull", -flow.sum())
    _flow(ev, "bull", "to_bull", flow.sum())

    # 7. external entries (generation 0 = purchased; cow parity unknown)
    e = r.entry_per_day
    if e > 0:
        unk = COW_PARITIES.index("unknown")
        dim = min(max(r.entry_dim, 0), N_DIM - 1)
        gest = min(max(r.entry_gestation, 0), N_GEST - 2)
        for state, share in r.entry_shares.items():
            n = e * share
            _flow(ev, state if state in STATES else "unknown", "entries", n)
            if state == "calf":
                s.calf[0, 0] += n
            elif state == "heifer_open":
                s.heifer_open[0] += n
            elif state == "heifer_pregnant":
                s.heifer_preg[0, gest] += n
            elif state == "milking":
                s.milk_open[unk, 0, dim] += n
            elif state == "dry_open":
                s.dry_open[unk, 0] += n
            elif state == "dry_pregnant":
                s.dry_preg[unk, 0, gest] += n
            elif state == "bull":
                s.bull += n
            else:
                s.unknown += n
        ev["external_entries"] = float(e)
    return ev


@dataclass
class MilkCurveArrays:
    """Expected litres per cow-day for the engine's milking compartments."""

    open_: np.ndarray  # (N_PAR, N_GEN, N_DIM)
    preg: np.ndarray  # (N_PAR, N_GEN, N_CB * N_GEST)

    @classmethod
    def from_yield(cls, yield_pgd: np.ndarray, preg_multiplier: np.ndarray | None = None
                   ) -> "MilkCurveArrays":
        """``yield_pgd``: (parity, generation, DIM >= N_DIM); ``preg_multiplier``: (N_GEST,)."""
        y = np.asarray(yield_pgd, dtype=float)[:, :, :N_DIM]
        mult = np.ones(N_GEST) if preg_multiplier is None else np.asarray(preg_multiplier)[:N_GEST]
        gest_of_flat = np.tile(np.arange(N_GEST), N_CB)
        preg = y[:, :, _DIM_OF_PREG_FLAT] * mult[gest_of_flat][None, None, :]
        return cls(open_=y, preg=preg)

    def litres(self, s: "OriginState") -> float:
        return float((s.milk_open * self.open_).sum()
                     + (s.milk_preg.reshape(N_PAR, N_GEN, -1) * self.preg).sum())


def project(
    start: OriginState, rates: RateSet, horizon_days: int, record_cells: bool = False,
    milk_curve: MilkCurveArrays | None = None, record_milk_mix: bool = False,
) -> Projection:
    """Project ``horizon_days`` days from ``start.origin`` (day 1 = the origin date).

    With ``milk_curve``, the daily frame also has ``curve_litres`` = sum over milking
    compartments of cows x expected yield (before the calibration factor k).
    """
    if horizon_days < 1:
        raise ValueError("horizon_days must be at least 1")
    s = start.copy()
    rows: list[dict] = []
    cell_frames: list[pd.DataFrame] = []
    mixes: list[np.ndarray] = []
    for t in range(horizon_days):
        day = start.origin + timedelta(days=t)
        events = step_day(s, rates)
        totals = s.state_totals()
        row = {"date": day}
        for state, col in STATE_TO_STOCK.items():
            row[col] = totals[state]
        row["n_herd"] = sum(totals.values())
        row["calves_female"] = float(s.calf[0].sum())
        row["calves_male"] = float(s.calf[1].sum())
        if milk_curve is not None:
            row["curve_litres"] = milk_curve.litres(s)
        if record_milk_mix:
            mixes.append(milking_mix(s))
        row.update(events)
        rows.append(row)
        if record_cells:
            cells = s.cells()
            cells.insert(0, "date", day)
            cell_frames.append(cells)
    daily = pd.DataFrame(rows)
    cells = pd.concat(cell_frames, ignore_index=True) if record_cells else None
    mix = np.stack(mixes) if record_milk_mix else None
    return Projection(origin=start.origin, daily=daily.fillna(0.0), cells=cells, final_state=s,
                      milk_mix=mix)


def milking_mix(s: OriginState) -> np.ndarray:
    """Milking cows by parity x 10-day DIM bin x pregnancy band, shape (N_PAR, N_DIM_BIN, 4)."""
    out = np.zeros((N_PAR, N_DIM_BIN, 4))
    out[:, :, 0] = s.milk_open.sum(1).reshape(N_PAR, N_DIM_BIN, 10).sum(-1)
    preg = s.milk_preg.sum(1).reshape(N_PAR, -1)
    for p in range(N_PAR):
        out[p] += np.bincount(_PREG_MIX_INDEX, weights=preg[p],
                              minlength=N_DIM_BIN * 4).reshape(N_DIM_BIN, 4)
    return out
