"""Milk baseline: herd milk = k x sum over cows of expected yield (lactation curve).

* The herd engine supplies cows by parity, generation, DIM and gestation day each
  projected day; ``MilkCurveArrays`` turns them into ``curve_litres``.
* k (calibration) is fitted per target source on 12 complete months that end two months
  before the origin month, so every conception used for those months had been recorded
  (35-day pregnancy-check lag) before the origin:
      k = sum(target litres) / sum(curve litres x scoreable share of the month).
  Shipments (before 2020-08) and DelPro (from 2020-08) measure different things, so each
  has its own k. A forecast uses the k of the source current at the origin; if that
  source has fewer than 3 usable months, the other source's k is used and the run is
  flagged ``source_switch``.
* Anchored k (default, ``k_mode="anchored"``): k = mean recorded litres over the last
  14 scoreable days before the origin (current source, within the last 28 days) divided
  by the curve litres of the starting herd (the herd on the day before the origin). Both
  are known at the origin. With fewer than 7 such days, the 12-month k is kept and the
  run is flagged ``k_window``. ``k_mode="window"`` always uses the 12-month k.
* Days that are not scoreable (gaps, suspect lows, no DelPro milk) are neither used for k
  nor scored, and never imputed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .categories import cow_parity_index, generation_index
from .data import DATA_START, LeakageError, add_months, check_before, month_start
from .herd_engine import N_GEST, MilkCurveArrays
from .lactation_curve import (
    CurveSet, fit_curve, fit_herd_shape, published_curve,
)

FITTED_FROM = date(2020, 9, 1)  # first origin with reliable per-cow data before it
FITTED_EVERYWHERE_RANGE = (date(2020, 8, 1), date(2023, 1, 1))  # sensitivity only
CURVE_MODES = ("published", "herd_fitted", "fitted_everywhere")
MIN_K_MONTHS = 3
MIN_SCOREABLE_SHARE = 0.8
K_MODES = ("anchored", "window")
ANCHOR_DAYS = 14
ANCHOR_LOOKBACK_DAYS = 28
ANCHOR_MIN_DAYS = 7


@dataclass(frozen=True)
class MilkConfig:
    curve_mode: str = "herd_fitted"  # shape before 2020-09 (decision: docs/milk_model.md)
    pregnancy_factor: bool = True
    generation_factor: bool = False
    k_months: int = 12
    k_mode: str = "anchored"  # anchored | window

    def tag(self) -> str:
        return (f"{self.curve_mode}_p{int(self.pregnancy_factor)}"
                f"_g{int(self.generation_factor)}_k{self.k_mode[0]}")


def calibration_window(origin: date, months: int = 12) -> tuple[date, date]:
    """[start, end) of the k window: complete months ending two months before the origin month."""
    end = add_months(month_start(origin), -2)
    return add_months(end, -months), end


@dataclass
class MilkHistory:
    """Aggregates loaded once for a backtest; every use is cut at the origin and guarded."""

    cowdays: pd.DataFrame  # month, parity_group, generation_group, dim_bin, preg_band, cow_days, max_date
    target: pd.DataFrame  # date, target_source, target_litres, is_scoreable

    def cowdays_before(self, end: date, origin: date) -> pd.DataFrame:
        part = self.cowdays[pd.to_datetime(self.cowdays["month"]).dt.date < end]
        return check_before(part, origin, "milking_cowdays")

    def target_before(self, origin: date) -> pd.DataFrame:
        part = self.target[pd.to_datetime(self.target["date"]).dt.date < origin]
        if len(part) and max(pd.to_datetime(part["date"]).dt.date) >= origin:
            raise LeakageError("target history reaches the origin")
        return part


def monthly_target(target: pd.DataFrame) -> pd.DataFrame:
    """Per month: scoreable litres, scoreable share, and the single source (or None)."""
    t = target.copy()
    t["month"] = [d.replace(day=1) for d in pd.to_datetime(t["date"]).dt.date]
    t["ok"] = t["is_scoreable"].fillna(False).astype(bool) & t["target_litres"].notna()
    g = t.groupby("month")
    out = pd.DataFrame({
        "days": g.size(),
        "ok_days": g["ok"].sum(),
        "litres": t[t["ok"]].groupby("month")["target_litres"].sum(),
    }).fillna({"litres": 0.0})
    src = t[t["ok"]].groupby("month")["target_source"].agg(lambda s: s.iloc[0] if s.nunique() == 1 else None)
    out["source"] = src
    out["share"] = out["ok_days"] / out["days"]
    return out


def curve_litres_by_month(cowdays: pd.DataFrame, curve: CurveSet) -> pd.Series:
    """Sum over cow-days of expected yield, per month (before k)."""
    if not len(cowdays):
        return pd.Series(dtype=float)
    y = curve.yield_array()
    p = cowdays["parity_group"].astype(str).map(cow_parity_index).to_numpy()
    g = cowdays["generation_group"].astype(str).map(generation_index).to_numpy()
    d = np.clip(cowdays["dim_bin"].to_numpy(dtype=int) + 5, 1, y.shape[2] - 1)
    mult = curve.preg_multiplier(400)
    band = cowdays["preg_band"].to_numpy(dtype=int)
    m = np.where(band < 0, 1.0, mult[np.clip(band, 0, 399)])
    lit = cowdays["cow_days"].to_numpy(dtype=float) * y[p, g, d] * m
    return pd.Series(lit, index=cowdays["month"].to_numpy()).groupby(level=0).sum()


def fit_k(curve_m: pd.Series, target_m: pd.DataFrame) -> dict[str, tuple[float, int]]:
    """k per source: (k, number of months used)."""
    out = {}
    tm = target_m[(target_m["share"] >= MIN_SCOREABLE_SHARE) & target_m["source"].notna()]
    for source, grp in tm.groupby("source"):
        months = [m for m in grp.index if m in curve_m.index and curve_m[m] > 0]
        if len(months) < MIN_K_MONTHS:
            continue
        num = grp.loc[months, "litres"].sum()
        den = float((curve_m[months] * grp.loc[months, "share"]).sum())
        if den > 0:
            out[str(source)] = (float(num / den), len(months))
    return out


@dataclass
class MilkSetup:
    origin: date
    curve: CurveSet
    arrays: MilkCurveArrays
    k: float
    k_source: str
    target_source: str | None
    flags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def current_source(target_hist: pd.DataFrame) -> str | None:
    ok = target_hist[target_hist["is_scoreable"].fillna(False).astype(bool) & target_hist["target_source"].notna()]
    return None if not len(ok) else str(ok.sort_values("date")["target_source"].iloc[-1])


def select_curve(source, origin: date, cfg: MilkConfig, hist: MilkHistory,
                 cache: dict | None = None) -> CurveSet:
    """Curve for this origin (cached per origin month: data before the month start only)."""
    key = (month_start(origin), cfg.tag())
    if cache is not None and key in cache:
        return cache[key]
    if cfg.curve_mode == "fitted_everywhere":
        stats = source.cow_curve_stats(*FITTED_EVERYWHERE_RANGE).drop(columns="max_date", errors="ignore")
        curve = fit_curve(stats, "fitted_everywhere", cfg.pregnancy_factor, cfg.generation_factor)
        if curve is None:
            raise ValueError("no reliable cow-days for the fitted_everywhere sensitivity run")
        curve.uses_later_information = True
    else:
        curve = None
        if origin >= FITTED_FROM:
            end = month_start(origin)
            stats = check_before(source.cow_curve_stats(DATA_START, end), origin, "cow_curve_stats")
            curve = fit_curve(stats, "fitted", cfg.pregnancy_factor, cfg.generation_factor)
        if curve is None and cfg.curve_mode == "herd_fitted":
            curve = _herd_fitted(origin, hist)
        if curve is None:
            curve = published_curve()
    if cache is not None:
        cache[key] = curve
    return curve


def _herd_fitted(origin: date, hist: MilkHistory) -> CurveSet | None:
    start, end = calibration_window(origin, 24)
    cd = hist.cowdays_before(end, origin)
    cd = cd[pd.to_datetime(cd["month"]).dt.date >= start]
    tm = monthly_target(hist.target_before(origin))
    tm = tm[(tm["share"] >= 0.95) & tm["source"].notna()]
    tm = tm[[start <= m < end for m in tm.index]]
    if not len(tm):
        return None
    main = tm["source"].mode().iloc[0]  # one source only: shipment and DelPro differ in level
    tm = tm[tm["source"] == main]
    target = tm["litres"] / tm["share"]
    agg = cd.groupby(["month", "dim_bin"], as_index=False)["cow_days"].sum()
    return fit_herd_shape(agg, target)


def prepare_milk(source, origin: date, cfg: MilkConfig, hist: MilkHistory,
                 cache: dict | None = None) -> MilkSetup:
    curve = select_curve(source, origin, cfg, hist, cache)
    arrays = MilkCurveArrays.from_yield(curve.yield_array(), curve.preg_multiplier(N_GEST))
    start, end = calibration_window(origin, cfg.k_months)
    cd = hist.cowdays_before(end, origin)
    cd = cd[pd.to_datetime(cd["month"]).dt.date >= start]
    target_hist = hist.target_before(origin)
    tm = monthly_target(target_hist)
    tm = tm[[start <= m < end for m in tm.index]]
    ks = fit_k(curve_litres_by_month(cd, curve), tm)
    src = current_source(target_hist)
    flags, notes = [], list(curve.notes)
    if curve.uses_later_information:
        flags.append("uses_later_information")
    if src in ks:
        k, k_source = ks[src][0], src
    elif ks:
        k_source = max(ks, key=lambda s: ks[s][1])
        k = ks[k_source][0]
        flags.append("source_switch")
    else:
        raise ValueError(f"no usable months to calibrate k before {origin}")
    notes.append(f"k: {k:.3f} from {k_source} ({ks[k_source][1]} months)")
    return MilkSetup(origin=origin, curve=curve, arrays=arrays, k=k, k_source=k_source,
                     target_source=src, flags=flags, notes=notes)


def anchor_k(setup: MilkSetup, target_hist: pd.DataFrame, start_state, cfg: MilkConfig) -> MilkSetup:
    """Replace k by the anchored k (see module docstring); modifies and returns ``setup``."""
    if cfg.k_mode != "anchored":
        return setup
    origin = setup.origin
    t = target_hist.copy()
    t["date"] = pd.to_datetime(t["date"]).dt.date
    ok = (t["is_scoreable"].fillna(False).astype(bool) & t["target_litres"].notna()
          & (t["date"] < origin) & (t["date"] >= origin - timedelta(days=ANCHOR_LOOKBACK_DAYS)))
    if setup.target_source is not None:
        ok &= t["target_source"] == setup.target_source
    recent = t[ok].sort_values("date").tail(ANCHOR_DAYS)
    start_litres = setup.arrays.litres(start_state)
    if len(recent) < ANCHOR_MIN_DAYS or start_litres <= 0:
        setup.flags.append("k_window")
        setup.notes.append("k: anchoring not possible (too few recent scoreable days), 12-month k kept")
        return setup
    window_k = setup.k
    setup.k = float(recent["target_litres"].mean() / start_litres)
    setup.k_source = f"anchored:{setup.target_source}"
    setup.notes.append(f"k: anchored {setup.k:.3f} on {len(recent)} recent days "
                       f"(12-month k was {window_k:.3f})")
    return setup
