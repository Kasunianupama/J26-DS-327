"""Build the engine's starting herd from aggregate inputs.

Stocks come from `model_input.day_cell` on the day before the origin (presence
intervals, which balance exactly). The clock distributions (days in milk, gestation
day) only *shape* those counts within each cell; they never change the totals.

Clock histograms are grouped counts, e.g. "n cows in parity 2, generation 1 at DIM 84,
gestation day 30". When a cell has no matching histogram rows, the shape falls back to
a pooled histogram and finally to a uniform spread; each fallback is reported in
``notes`` as an aggregate count.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .categories import (
    GENERATIONS,
    DIM_BAND_BOUNDS,
    DIM_BANDS,
    STATES,
    cow_parity_index,
    generation_index,
)
from .herd_engine import CB_WIDTH, N_CB, N_DIM, N_GEST, OriginState

UNIFORM_DRY_GEST = (220, 279)
UNIFORM_MAX_GEST = 279
# A recorded conception older than this with no calving yet is not a live pregnancy
# (typically a loss recorded later or never). Such clocks would otherwise sit at the
# end of the gestation range and all "calve" on the first projected day.
MAX_LIVE_GEST = 300


def _first_nonempty(hist: pd.DataFrame, filters: list[dict]) -> pd.DataFrame | None:
    for flt in filters:
        sub = hist
        for col, value in flt.items():
            sub = sub[sub[col] == value]
        if len(sub) and sub["n"].sum() > 0:
            return sub
    return None


def _band_rows(hist: pd.DataFrame, band: str) -> pd.DataFrame:
    if band not in DIM_BANDS:
        return hist
    lo, hi = DIM_BAND_BOUNDS[DIM_BANDS.index(band)]
    mask = hist["dim"] >= lo
    if hi is not None:
        mask &= hist["dim"] <= hi
    return hist[mask]


def build_origin_state(
    origin: date,
    cells: pd.DataFrame,
    milking_clock: pd.DataFrame,
    dry_clock: pd.DataFrame,
    heifer_clock: pd.DataFrame,
    pregnancy_check_lag_days: int = 35,
    max_live_gest: int | None = None,
    conception_per_ai: float = 0.0,
    calf_sex: pd.DataFrame | None = None,
) -> tuple[OriginState, list[str]]:
    """Starting herd. ``max_live_gest``: recorded conceptions older than this with no
    calving are not live pregnancies. ``conception_per_ai``: probability that a milking
    cow whose last service is too recent to be confirmed is pregnant. ``calf_sex``:
    animals under one year by sex and generation, used to split calf counts (without
    it every calf is held in the female row, i.e. one calf group)."""
    male_share = _male_share_by_generation(calf_sex)
    max_live = MAX_LIVE_GEST if max_live_gest is None else max_live_gest
    s = OriginState(origin=origin)
    notes: list[str] = []
    uniform = {"milking": 0.0, "dry_pregnant": 0.0, "heifer_pregnant": 0.0}

    cells = cells.copy()
    cells["state"] = cells["state"].where(cells["state"].isin(STATES), "unknown")
    for col in ("parity_group", "dim_band", "generation_group"):
        cells[col] = cells[col].fillna("unknown").astype(str)

    mc = milking_clock.copy()
    if len(mc):
        mc["gest"] = mc["gest"].astype(float)
        mc["dim"] = mc["dim"].astype(int)
        stale = mc["gest"] > max_live
        _note_stale(notes, "milking clock", mc, stale, max_live, "treated as open")
        mc.loc[stale, "gest"] = np.nan
    dc = dry_clock.copy()
    if len(dc):
        dc["gest"] = dc["gest"].astype(float)
        stale = dc["gest"] > max_live
        _note_stale(notes, "dry clock", dc, stale, max_live, "left out of the gestation shape")
        dc = dc[~stale]

    grouped = cells.groupby(
        ["state", "parity_group", "dim_band", "generation_group"], as_index=False
    )["n"].sum()

    for row in grouped.itertuples(index=False):
        n = float(row.n)
        if n <= 0:
            continue
        g = generation_index(row.generation_group)
        p = cow_parity_index(row.parity_group)
        state = row.state
        if state == "calf":
            m = male_share[g]
            s.calf[0, g] += n * (1.0 - m)
            s.calf[1, g] += n * m
        elif state == "heifer_open":
            s.heifer_open[g] += n
        elif state == "bull":
            s.bull += n
        elif state == "unknown":
            s.unknown += n
        elif state == "dry_open":
            s.dry_open[p, g] += n
        elif state == "milking":
            _spread_milking(s, mc, row.parity_group, row.dim_band, row.generation_group,
                            p, g, n, uniform, conception_per_ai)
        elif state == "dry_pregnant":
            sub = None
            if len(dc):
                preg = dc[dc["gest"].notna()]
                sub = _first_nonempty(
                    preg,
                    [
                        {"parity_group": row.parity_group,
                         "generation_group": row.generation_group},
                        {"parity_group": row.parity_group},
                        {},
                    ],
                )
            gest, w = _gest_weights(sub, *UNIFORM_DRY_GEST)
            if sub is None:
                uniform["dry_pregnant"] += n
            np.add.at(s.dry_preg[p, g], gest, n * w)
        elif state == "heifer_pregnant":
            sub = None
            hc = heifer_clock[heifer_clock["gest"].astype(float) <= max_live] if len(heifer_clock) else heifer_clock
            if len(hc):
                sub = _first_nonempty(
                    hc, [{"generation_group": row.generation_group}, {}]
                )
            gest, w = _gest_weights(sub, pregnancy_check_lag_days, UNIFORM_MAX_GEST)
            if sub is None:
                uniform["heifer_pregnant"] += n
            np.add.at(s.heifer_preg[g], gest, n * w)

    for state, n in uniform.items():
        if n > 0:
            notes.append(f"{state}: {n:.0f} animals spread uniformly (no clock histogram)")
    return s, notes


def _male_share_by_generation(calf_sex: pd.DataFrame | None) -> np.ndarray:
    """Male share of young animals per generation, falling back to the pooled share."""
    out = np.zeros(len(GENERATIONS))
    if calf_sex is None or not len(calf_sex):
        return out
    cs = calf_sex[calf_sex["sex"].isin(["female", "male"])]
    tot = cs.groupby("sex")["n"].sum()
    if tot.sum() <= 0:
        return out
    pooled = float(tot.get("male", 0.0)) / float(tot.sum())
    out[:] = pooled
    for gen, grp in cs.groupby("generation_group"):
        t = grp.groupby("sex")["n"].sum()
        if t.sum() > 0:
            out[generation_index(str(gen))] = float(t.get("male", 0.0)) / float(t.sum())
    return out


def _note_stale(notes: list[str], name: str, clock: pd.DataFrame, stale: pd.Series,
                max_live: int, action: str) -> None:
    preg = clock["gest"].notna()
    if stale.any() and clock.loc[preg, "n"].sum() > 0:
        share = 100.0 * clock.loc[stale, "n"].sum() / clock.loc[preg, "n"].sum()
        notes.append(f"{name}: {share:.1f}% of recorded conceptions older than "
                     f"{max_live} days, {action}")


def _gest_weights(sub: pd.DataFrame | None, lo: int, hi: int) -> tuple[np.ndarray, np.ndarray]:
    if sub is None:
        gest = np.arange(lo, hi + 1)
        return gest, np.full(len(gest), 1.0 / len(gest))
    agg = sub.groupby("gest")["n"].sum()
    gest = np.clip(agg.index.to_numpy().astype(int), 0, N_GEST - 2)
    w = agg.to_numpy(dtype=float)
    return gest, w / w.sum()


def _spread_milking(
    s: OriginState,
    mc: pd.DataFrame,
    parity_group: str,
    band: str,
    generation_group: str,
    p: int,
    g: int,
    n: float,
    uniform: dict[str, float],
    conception_per_ai: float = 0.0,
) -> None:
    sub = None
    if len(mc):
        in_band = _band_rows(mc, band)
        sub = _first_nonempty(
            in_band,
            [
                {"parity_group": parity_group, "generation_group": generation_group},
                {"parity_group": parity_group},
                {},
            ],
        )
    if sub is None:
        uniform["milking"] += n
        if band in DIM_BANDS:
            lo, hi = DIM_BAND_BOUNDS[DIM_BANDS.index(band)]
            hi = 400 if hi is None else hi
        else:
            lo, hi = 0, 305
        dims = np.arange(lo, hi + 1)
        np.add.at(s.milk_open[p, g], dims, n / len(dims))
        return
    w = sub["n"].to_numpy(dtype=float)
    w = n * w / w.sum()
    dim = np.clip(sub["dim"].to_numpy(), 0, N_DIM - 1)
    gest = sub["gest"].to_numpy()
    if "recent_ai_gest" in sub.columns and conception_per_ai > 0:
        # Unconfirmed recent service: pregnant with probability conception_per_ai.
        recent = sub["recent_ai_gest"].to_numpy(dtype=float)
        unconfirmed = np.isnan(gest) & ~np.isnan(recent)
        if unconfirmed.any():
            dim = np.concatenate([dim, dim[unconfirmed]])
            gest = np.concatenate([gest, recent[unconfirmed]])
            w_preg = w[unconfirmed] * conception_per_ai
            w = w.copy()
            w[unconfirmed] -= w_preg
            w = np.concatenate([w, w_preg])
    is_open = np.isnan(gest)
    np.add.at(s.milk_open[p, g], dim[is_open], w[is_open])
    if (~is_open).any():
        gp = np.clip(gest[~is_open].astype(int), 0, N_GEST - 2)
        cb = np.clip((dim[~is_open] - gp) // CB_WIDTH, 0, N_CB - 1)
        np.add.at(s.milk_preg[p, g], (cb, gp), w[~is_open])
