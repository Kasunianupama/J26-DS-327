"""Lactation curves: expected daily yield of one cow by parity, days in milk (DIM),
pregnancy stage and (optionally) generation.

Wood curve: y(d) = a * d**b * exp(-c * d), d = days in milk (d >= 1).

Sources, chosen per origin (docs/milk_model.md):

* ``fitted``: fitted on the farm's reliable cow-days (core.cow_day.is_reliable) dated
  before the origin. Reliable per-cow records exist only from 2020-08, so this is used
  for origins from 2020-09 when enough data exists.
* ``published``: Wood shape for Jersey crossbred cows, Mandal et al. 2026 (Indian
  Journal of Dairy Science): b = 0.340, c = 0.108 per fortnight (fitted on fortnightly
  test days; converted here to c = 0.108 / 14 per day). ASSUMED time unit until the
  full paper is checked. External knowledge, so no leakage.
* ``herd_fitted``: shape (b, c) fitted to the farm's own past herd milk, given how many
  cows were at each DIM each month (no per-cow yields needed, no leakage).
* ``fitted_everywhere``: sensitivity only, the 2020-08 – 2022-12 fitted curve used at
  every origin. Uses later information and is excluded from the H1 claim.

Only the shape matters for forecasting: the level is rescaled by the calibration
factor k in ``milk_baseline``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .categories import COW_PARITIES, GENERATIONS, cow_parity_index, generation_index

N_PAR = len(COW_PARITIES)
N_GEN = len(GENERATIONS)
MAX_DIM = 1000

PUBLISHED_B = 0.340
PUBLISHED_C_PER_DAY = 0.108 / 14.0
PUBLISHED_REF = "Mandal et al. 2026 (Jersey crossbred, Wood; c converted from per-fortnight)"

FIT_DIM_RANGE = (5, 400)
MIN_FIT_COW_DAYS = 2000
MIN_FIT_DIMS = 60
# Pregnancy bands (days pregnant) for the pregnancy factor; < 150 days is the reference.
PREG_BANDS = (150, 200)
# Search grid for the herd-fitted shape; peak day b/c is kept within 20..120 days.
HERD_B_GRID = np.round(np.arange(0.05, 0.61, 0.025), 3)
HERD_C_GRID = np.round(np.arange(0.0010, 0.0121, 0.0005), 5)


def wood(d: np.ndarray, a: float, b: float, c: float) -> np.ndarray:
    d = np.maximum(np.asarray(d, dtype=float), 1.0)
    return a * d ** b * np.exp(-c * d)


@dataclass
class CurveSet:
    """Per-parity Wood parameters plus multiplicative factors."""

    params: dict[int, tuple[float, float, float]]  # parity index -> (a, b, c)
    source: str
    preg_factor: dict[int, float] = field(default_factory=dict)  # band start -> multiplier
    gen_factor: np.ndarray = field(default_factory=lambda: np.ones(N_GEN))
    uses_later_information: bool = False
    notes: tuple[str, ...] = ()

    def yield_array(self) -> np.ndarray:
        """Expected litres per cow-day, shape (parity, generation, DIM)."""
        d = np.arange(MAX_DIM)
        out = np.zeros((N_PAR, N_GEN, MAX_DIM))
        for p in range(N_PAR):
            a, b, c = self.params.get(p, self.params[max(self.params)])
            out[p] = wood(d, a, b, c)[None, :] * self.gen_factor[:, None]
        return out

    def preg_multiplier(self, n_gest: int) -> np.ndarray:
        """Multiplier by gestation day (1 below the first band)."""
        m = np.ones(n_gest)
        for start in sorted(self.preg_factor):
            m[start:] = self.preg_factor[start]
        return m


def published_curve() -> CurveSet:
    params = {p: (1.0, PUBLISHED_B, PUBLISHED_C_PER_DAY) for p in range(N_PAR)}
    return CurveSet(params=params, source="published", notes=(f"curve: {PUBLISHED_REF}",))


def fit_wood_wls(dim: np.ndarray, mean_yield: np.ndarray, n: np.ndarray) -> tuple[float, float, float]:
    """Weighted least squares on ln y = ln a + b ln d - c d."""
    keep = (mean_yield > 0) & (n > 0) & (dim >= 1)
    d, y, w = dim[keep].astype(float), mean_yield[keep].astype(float), n[keep].astype(float)
    X = np.column_stack([np.ones_like(d), np.log(d), -d])
    W = np.sqrt(w)
    coef, *_ = np.linalg.lstsq(X * W[:, None], np.log(y) * W, rcond=None)
    return float(np.exp(coef[0])), float(coef[1]), float(coef[2])


def fit_curve(stats: pd.DataFrame, source: str = "fitted", pregnancy_factor: bool = True,
              generation_factor: bool = False) -> CurveSet | None:
    """Fit Wood curves per parity from aggregated reliable cow-days.

    ``stats`` columns: parity_group, generation_group, dim, preg_band (-1 open, else band
    start in days pregnant, 0 for < 150), n (cow-days), sum_yield (litres). Returns None if
    there are too few data.
    """
    if not len(stats):
        return None
    s = stats[(stats["dim"] >= FIT_DIM_RANGE[0]) & (stats["dim"] <= FIT_DIM_RANGE[1])].copy()
    if s["n"].sum() < MIN_FIT_COW_DAYS:
        return None
    s["p"] = s["parity_group"].astype(str).map(cow_parity_index)
    # Shape from open and early-pregnant cows (reference), so pregnancy is a separate factor.
    ref = s[s["preg_band"] < PREG_BANDS[0]] if pregnancy_factor else s
    pooled = ref.groupby("dim")[["n", "sum_yield"]].sum()
    if len(pooled) < MIN_FIT_DIMS:
        return None
    pooled_params = fit_wood_wls(pooled.index.to_numpy(), (pooled["sum_yield"] / pooled["n"]).to_numpy(),
                                 pooled["n"].to_numpy())
    params: dict[int, tuple[float, float, float]] = {}
    notes = []
    for p in range(N_PAR):
        g = ref[ref["p"] == p].groupby("dim")[["n", "sum_yield"]].sum()
        if len(g) >= MIN_FIT_DIMS and g["n"].sum() >= MIN_FIT_COW_DAYS / 2:
            a, b, c = fit_wood_wls(g.index.to_numpy(), (g["sum_yield"] / g["n"]).to_numpy(), g["n"].to_numpy())
            if b <= 0 or c <= 0:  # implausible shape: use the pooled curve
                a, b, c = pooled_params
                notes.append(f"curve: parity {COW_PARITIES[p]} shape implausible, pooled used")
            params[p] = (a, b, c)
        else:
            params[p] = pooled_params
            notes.append(f"curve: parity {COW_PARITIES[p]} too few cow-days, pooled used")
    curve = CurveSet(params=params, source=source, notes=tuple(notes))

    pred = np.array([wood(d, *params[p])[()] for d, p in zip(s["dim"], s["p"])])
    s["pred"] = pred * s["n"]
    if pregnancy_factor:
        base = s[s["preg_band"] < PREG_BANDS[0]]
        ref_ratio = base["sum_yield"].sum() / base["pred"].sum()
        for start in PREG_BANDS:
            band = s[s["preg_band"] == start]
            if band["n"].sum() >= 500:
                ratio = band["sum_yield"].sum() / band["pred"].sum() / ref_ratio
                curve.preg_factor[start] = float(np.clip(ratio, 0.6, 1.1))
    if generation_factor:
        tot = s["sum_yield"].sum() / s["pred"].sum()
        for gen, grp in s.groupby("generation_group"):
            if grp["n"].sum() >= 1000:
                r = grp["sum_yield"].sum() / grp["pred"].sum() / tot
                curve.gen_factor[generation_index(str(gen))] = float(np.clip(r, 0.7, 1.3))
    return curve


def fit_herd_shape(cowdays: pd.DataFrame, target: pd.Series) -> CurveSet | None:
    """Fit one Wood shape (b, c) to past herd milk.

    ``cowdays``: month, dim_bin, cow_days (milking cows by 10-day DIM bin per month).
    ``target``: litres per month (complete, single-source months only). For each (b, c)
    on a grid, the level is the least-squares k; the pair with the smallest squared error
    is kept. Needs at least 12 months.
    """
    months = sorted(set(cowdays["month"]) & set(target.index))
    if len(months) < 12:
        return None
    piv = (cowdays[cowdays["month"].isin(months)]
           .pivot_table(index="month", columns="dim_bin", values="cow_days", aggfunc="sum", fill_value=0.0)
           .reindex(months))
    d = piv.columns.to_numpy(dtype=float) + 5.0
    N = piv.to_numpy()
    y = target.reindex(months).to_numpy(dtype=float)
    best = None
    for b in HERD_B_GRID:
        for c in HERD_C_GRID:
            if not 20 <= b / c <= 120:
                continue
            x = N @ wood(d, 1.0, b, c)
            k = float(x @ y / (x @ x)) if x @ x > 0 else 0.0
            sse = float(((y - k * x) ** 2).sum())
            if best is None or sse < best[0]:
                best = (sse, b, c, k)
    if best is None:
        return None
    _, b, c, k = best
    params = {p: (1.0, float(b), float(c)) for p in range(N_PAR)}
    return CurveSet(params=params, source="herd_fitted",
                    notes=(f"curve: herd-fitted shape b={b:.3f}, c={c:.5f}/day, peak day {b / c:.0f}",))


def curve_summary(curve: CurveSet) -> pd.DataFrame:
    """Peak day, relative peak and 305-day relative yield per parity (aggregates only)."""
    rows = []
    d = np.arange(1, 306)
    for p in range(N_PAR):
        a, b, c = curve.params[p]
        y = wood(d, a, b, c)
        rows.append((COW_PARITIES[p], a, b, c, b / c if c > 0 else np.nan, float(y.max()), float(y.sum())))
    return pd.DataFrame(rows, columns=["parity", "a", "b", "c_per_day", "peak_day", "peak_yield", "yield_305d"])
