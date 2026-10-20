"""Explanations that add up exactly (Step 5).

Milk (Shapley). The model computes herd milk per day as

    milk = k * N * sum_p pi_p * sum_d sigma_{d|p} * sum_b rho_{b|p,d} * Y[p, d, b]

with N milking cows, pi the parity mix, sigma the lactation-stage (DIM) mix within
parity, rho the pregnancy mix within parity x stage, Y the curve yield per cow-day and k
the yield level. The change between two months is split over the five factors
{herd_size, parity_mix, stage_mix, pregnancy_mix, yield_level} by Shapley values: each
factor's share is averaged over all orders of switching it from the old month to the new
one. The shares sum exactly to the model change. For past months the residual
(actual change - model change) is reported as its own row; it holds everything the
model does not represent (heat, health, feed, recording).

* Past month m: N and the mixes from milking cow-days (core.lactation); k_m = actual
  milk / curve milk of the month before (the level known at the start of month m).
* Forecast month h: N and the mixes from the engine projection; k is the anchored k
  (constant, so yield_level is 0 within the forecast).

Herd flows. Each month's change in a state count is the sum of its flows (calvings in,
dry-offs out, exits out, ...), recorded by the engine. Calvings are split into
"determined" (from pregnancies already in the herd at the origin) and "rate-driven"
(from conceptions projected after it). The engine is linear in its compartments, so a
second projection without new conceptions gives the determined part exactly.

Mastitis. Expected episodes = projected milking cow-days x episode rate, reported for
the 12 months before the origin and for the reference period with consistent recording
(2016-01 - 2018-12, only when it ended before the origin), each labelled with its period.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from itertools import combinations
from math import factorial

import numpy as np
import pandas as pd

from .categories import COW_PARITIES, cow_parity_index
from .data import add_months, month_start
from .herd_engine import N_DIM_BIN, PREG_BAND_VALUES, RateSet, milking_mix, project
from .lactation_curve import CurveSet, wood

MILK_FACTORS = ("herd_size", "parity_mix", "stage_mix", "pregnancy_mix", "yield_level")
MILK_SERIES = "herd_milk_litres_per_day"
REFERENCE_MASTITIS = (date(2016, 1, 1), date(2019, 1, 1))


# ----------------------------------------------------------------- Shapley

def shapley(value, factors: tuple[str, ...]) -> dict[str, float]:
    """Exact Shapley values. ``value(S)`` = outcome with the factors in S set to 'new'."""
    n = len(factors)
    cache: dict[frozenset, float] = {}

    def v(s: frozenset) -> float:
        if s not in cache:
            cache[s] = float(value(s))
        return cache[s]

    out = {}
    for f in factors:
        others = [x for x in factors if x != f]
        total = 0.0
        for size in range(n):
            w = factorial(size) * factorial(n - size - 1) / factorial(n)
            for combo in combinations(others, size):
                s = frozenset(combo)
                total += w * (v(s | {f}) - v(s))
        out[f] = total
    return out


def yield_table(curve: CurveSet) -> np.ndarray:
    """Expected litres per cow-day, shape (parity, DIM bin, pregnancy band); k = 1."""
    d = np.arange(N_DIM_BIN) * 10 + 5
    mult = curve.preg_multiplier(400)
    band_mult = np.array([1.0] + [mult[b] for b in PREG_BAND_VALUES[1:]])
    out = np.zeros((len(COW_PARITIES), N_DIM_BIN, 4))
    for p in range(len(COW_PARITIES)):
        out[p] = wood(d, *curve.params[p])[:, None] * band_mult[None, :]
    return out


def _parts(mix: np.ndarray, days: float, other: np.ndarray):
    """N, pi, sigma, rho from a mix (P, D, B) of cow-days; empty cells borrow ``other``'s."""
    tot = mix.sum()
    n = tot / days
    pi = mix.sum(axis=(1, 2)) / tot if tot > 0 else np.zeros(mix.shape[0])
    pd_ = mix.sum(axis=2)
    o_pd = other.sum(axis=2)
    with np.errstate(divide="ignore", invalid="ignore"):
        sigma = pd_ / pd_.sum(axis=1, keepdims=True)
        s_other = o_pd / o_pd.sum(axis=1, keepdims=True)
        rho = mix / pd_[:, :, None]
        r_other = other / o_pd[:, :, None]
    sigma = np.where(np.isfinite(sigma), sigma, np.nan_to_num(s_other))
    rho = np.where(np.isfinite(rho), rho, np.nan_to_num(r_other))
    return n, pi, sigma, rho


def milk_per_day(n, pi, sigma, rho, k, y) -> float:
    return float(k * n * (pi[:, None, None] * sigma[:, :, None] * rho * y).sum())


def milk_shapley(mix0: np.ndarray, days0: float, k0: float, mix1: np.ndarray, days1: float,
                 k1: float, y: np.ndarray) -> tuple[dict[str, float], float, float]:
    """Shapley split of the model change in litres/day between two months.

    Returns (contributions, model value old, model value new)."""
    old = dict(zip(("herd_size", "parity_mix", "stage_mix", "pregnancy_mix"), _parts(mix0, days0, mix1)))
    new = dict(zip(("herd_size", "parity_mix", "stage_mix", "pregnancy_mix"), _parts(mix1, days1, mix0)))
    old["yield_level"], new["yield_level"] = k0, k1

    def value(s: frozenset) -> float:
        g = {f: (new if f in s else old)[f] for f in MILK_FACTORS}
        return milk_per_day(g["herd_size"], g["parity_mix"], g["stage_mix"], g["pregnancy_mix"],
                            g["yield_level"], y)

    contrib = shapley(value, MILK_FACTORS)
    return contrib, value(frozenset()), value(frozenset(MILK_FACTORS))


def mix_from_cowdays(cowdays: pd.DataFrame) -> dict[date, np.ndarray]:
    """Monthly milking mixes (P, D, B) of cow-days from ``milking_cowdays`` rows."""
    out: dict[date, np.ndarray] = {}
    band_idx = {v: i for i, v in enumerate(PREG_BAND_VALUES)}
    for m, g in cowdays.groupby("month"):
        mix = np.zeros((len(COW_PARITIES), N_DIM_BIN, 4))
        p = g["parity_group"].astype(str).map(cow_parity_index).to_numpy()
        d = np.minimum(g["dim_bin"].to_numpy(dtype=int) // 10, N_DIM_BIN - 1)
        b = g["preg_band"].map(band_idx).fillna(0).to_numpy(dtype=int)
        np.add.at(mix, (p, d, b), g["cow_days"].to_numpy(dtype=float))
        out[pd.Timestamp(m).date()] = mix
    return out


def _days_in_month(m: date) -> int:
    return (add_months(m, 1) - m).days


def explain_past_milk(cowdays: pd.DataFrame, monthly_actual: pd.DataFrame, curve: CurveSet,
                      origin: date, months: int = 12) -> pd.DataFrame:
    """Past months before ``origin``: Shapley factors + residual, litres/day.

    ``monthly_actual``: index month, columns litres_per_day (scoreable months) and source.
    Months whose own or previous two months are missing, or that change source, are
    skipped (reported with factor 'skipped')."""
    y = yield_table(curve)
    mixes = mix_from_cowdays(cowdays)
    rows = []
    first = add_months(month_start(origin), -months)
    m = first
    while m < month_start(origin):
        m1, m2 = add_months(m, -1), add_months(m, -2)
        need = [m, m1, m2]
        ok = all(x in mixes and x in monthly_actual.index and pd.notna(monthly_actual.loc[x, "litres_per_day"])
                 for x in need)
        if ok and monthly_actual.loc[need, "source"].nunique() == 1:
            curve_l = {x: milk_per_day(*_parts(mixes[x], _days_in_month(x), mixes[x]), 1.0, y) for x in need}
            a = monthly_actual["litres_per_day"]
            k_new = a[m1] / curve_l[m1]
            k_old = a[m2] / curve_l[m2]
            contrib, v_old, v_new = milk_shapley(mixes[m1], _days_in_month(m1), k_old,
                                                 mixes[m], _days_in_month(m), k_new, y)
            for f, c in contrib.items():
                rows.append((origin, m, "past", f, c))
            rows.append((origin, m, "past", "residual", (a[m] - a[m1]) - (v_new - v_old)))
            rows.append((origin, m, "past", "actual_change", a[m] - a[m1]))
        else:
            rows.append((origin, m, "past", "skipped", np.nan))
        m = add_months(m, 1)
    return _attr_frame(rows)


def starting_mix(state, origin: date) -> np.ndarray:
    """The engine's starting herd (day before the origin, from day_cell) as a month of
    cow-days for the month before the origin, so the first forecast month is compared
    with the same data source the forecast starts from."""
    return milking_mix(state) * _days_in_month(add_months(month_start(origin), -1))


def explain_forecast_milk(milk_mix: np.ndarray, dates: list[date], k: float, curve: CurveSet,
                          last_month_mix: np.ndarray | None, origin: date) -> pd.DataFrame:
    """Forecast months: Shapley factors of month-on-month change (litres/day).

    The first forecast month is compared with ``last_month_mix`` at the same k: use
    ``starting_mix`` (the engine's starting herd). Records rebuilt from core.lactation
    differ from day_cell by up to ~9 % in 2025-26, which would show as a false
    herd-size step in the first month."""
    y = yield_table(curve)
    by_month: dict[date, list[int]] = {}
    for i, d in enumerate(dates):
        by_month.setdefault(d.replace(day=1), []).append(i)
    months = [m for m in sorted(by_month) if len(by_month[m]) == _days_in_month(m)]
    rows = []
    prev_mix, prev_days = None, None
    if last_month_mix is not None:
        lm = add_months(month_start(origin), -1)
        prev_mix, prev_days = last_month_mix, _days_in_month(lm)
    for m in months:
        mix = milk_mix[by_month[m]].sum(axis=0)
        if prev_mix is not None:
            contrib, _, _ = milk_shapley(prev_mix, prev_days, k, mix, _days_in_month(m), k, y)
            for f, c in contrib.items():
                rows.append((origin, m, "forecast", f, c))
        prev_mix, prev_days = mix, _days_in_month(m)
    return _attr_frame(rows)


def _attr_frame(rows) -> pd.DataFrame:
    f = pd.DataFrame(rows, columns=["origin_date", "target_period", "kind", "factor", "contribution"])
    f.insert(2, "grain", "monthly")
    f.insert(3, "series", MILK_SERIES)
    return f


# ----------------------------------------------------------------- herd flows

def herd_flows(daily: pd.DataFrame, origin: date) -> pd.DataFrame:
    """Monthly sums of the engine's flows per state, plus the stock change they explain."""
    d = daily.copy()
    d["month"] = [x.replace(day=1) for x in pd.to_datetime(d["date"]).dt.date]
    cols = [c for c in d.columns if c.startswith("flow|")]
    rows = []
    for m, g in d.groupby("month"):
        if len(g) != _days_in_month(m):
            continue
        for c in cols:
            _, state, name = c.split("|")
            rows.append((origin, m, "monthly", state, name, float(g[c].sum())))
    return pd.DataFrame(rows, columns=["origin_date", "target_period", "grain", "series", "factor",
                                       "contribution"])


def without_new_conceptions(rates: RateSet) -> RateSet:
    """Same rates with every new conception switched off (pregnancies at origin unchanged)."""
    return replace(rates, conc_heifer=0.0, conc_dry=0.0, conc_cow=np.zeros_like(rates.conc_cow))


def calving_split(state, rates: RateSet, horizon_days: int, origin: date) -> pd.DataFrame:
    """Monthly calvings split into determined (pipeline at origin) and rate-driven."""
    full = project(state, rates, horizon_days).daily
    pipe = project(state, without_new_conceptions(rates), horizon_days).daily
    f = pd.DataFrame({"date": full["date"], "total": full["calvings"], "determined": pipe["calvings"]})
    f["rate_driven"] = f["total"] - f["determined"]
    f["month"] = [x.replace(day=1) for x in pd.to_datetime(f["date"]).dt.date]
    rows = []
    for m, g in f.groupby("month"):
        if len(g) != _days_in_month(m):
            continue
        for part in ("determined", "rate_driven"):
            rows.append((origin, m, "monthly", "calvings", part, float(g[part].sum())))
    return pd.DataFrame(rows, columns=["origin_date", "target_period", "grain", "series", "factor",
                                       "contribution"])


# ----------------------------------------------------------------- mastitis

def mastitis_rates(health: pd.DataFrame, milking_days: pd.Series, origin: date) -> list[tuple[str, float]]:
    """Episodes per milking cow-day for labelled periods that ended before the origin.

    ``health``: month, mastitis_episodes; ``milking_days``: milking cow-days by month."""
    out = []
    periods = [(add_months(month_start(origin), -12), month_start(origin), "last 12 months")]
    if REFERENCE_MASTITIS[1] <= month_start(origin):
        periods.append((*REFERENCE_MASTITIS, "reference 2016-2018"))
    for start, end, label in periods:
        h = health[[start <= pd.Timestamp(m).date() < end for m in health["month"]]]
        md = milking_days[[start <= pd.Timestamp(m).date() < end for m in milking_days.index]]
        if md.sum() > 0:
            out.append((f"{label} ({start:%Y-%m} to {add_months(end, -1):%Y-%m})",
                        float(h["mastitis_episodes"].sum()) / float(md.sum())))
    return out


def expected_mastitis(daily: pd.DataFrame, rates: list[tuple[str, float]], origin: date) -> pd.DataFrame:
    d = daily.copy()
    d["month"] = [x.replace(day=1) for x in pd.to_datetime(d["date"]).dt.date]
    rows = []
    for m, g in d.groupby("month"):
        if len(g) != _days_in_month(m):
            continue
        for label, rate in rates:
            rows.append((origin, m, "monthly", "mastitis_expected_episodes", f"rate: {label}",
                         float(g["milking"].sum()) * rate))
    return pd.DataFrame(rows, columns=["origin_date", "target_period", "grain", "series", "factor",
                                       "contribution"])


# ----------------------------------------------------------------- generation

def generation_composition(cells: pd.DataFrame) -> pd.DataFrame:
    """Monthly mean animals by stage group and generation from projected cells."""
    c = cells.copy()
    c["month"] = [x.replace(day=1) for x in pd.to_datetime(c["date"]).dt.date]
    group = {"calf": "calves", "heifer_open": "heifers", "heifer_pregnant": "heifers",
             "milking": "cows", "dry_open": "cows", "dry_pregnant": "cows"}
    c["group"] = c["state"].map(group)
    c = c.dropna(subset=["group"])
    days = c.groupby("month")["date"].nunique()
    tot = c.groupby(["month", "group", "generation_group"])["n"].sum().reset_index()
    tot["mean_animals"] = tot["n"] / tot["month"].map(days)
    return tot.drop(columns="n")
