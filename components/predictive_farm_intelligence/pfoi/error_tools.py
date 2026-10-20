"""Tools on backtest error tables: bias correction and empirical intervals.

Both use only errors whose target period had ended by the origin (known at the origin).
Error tables have columns origin, grain, horizon, period_end, series, model, forecast,
actual, error (= forecast - actual).
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

CORRECTION_LOOKBACK_DAYS = 730
CORRECTION_MIN_ERRORS = 6
INTERVAL_MIN_ERRORS = 12
INTERVAL_QUANTILES = (0.05, 0.95)
COVERAGE_FROM = date(2018, 1, 1)


def _known_mask(origins: np.ndarray, ends: np.ndarray, i: int, lookback_days: int | None):
    mask = ends <= origins[i]
    if lookback_days is not None:
        mask &= origins >= origins[i] - np.timedelta64(lookback_days, "D")
    return mask


def bias_corrected(errors: pd.DataFrame, base_model: str = "herd_engine",
                   new_model: str | None = None,
                   lookback_days: int = CORRECTION_LOOKBACK_DAYS,
                   min_errors: int = CORRECTION_MIN_ERRORS,
                   breaks: list | None = None) -> pd.DataFrame:
    """Forecasts of ``base_model`` minus its own mean past error (same grain, series, horizon).

    Only errors whose target period had ended by the origin, from origins in the previous
    ``lookback_days``, are used. With fewer than ``min_errors`` the raw forecast is kept.
    With ``breaks`` (``breaks.detect_breaks``), only errors from origins on or after the
    latest break known at the origin are used (PP1 improvement 1a).
    """
    from .breaks import since_mask

    new_model = new_model or f"{base_model}_corrected"
    eng = errors[errors["model"] == base_model]
    out = []
    for _, g in eng.groupby(["grain", "series", "horizon"]):
        g = g.sort_values("origin")
        origins = pd.to_datetime(g["origin"]).to_numpy()
        ends = pd.to_datetime(g["period_end"]).to_numpy()
        err = g["error"].to_numpy(dtype=float)
        corr = np.zeros(len(g))
        for i in range(len(g)):
            mask = _known_mask(origins, ends, i, lookback_days)
            if breaks:
                mask &= since_mask(origins, origins[i], breaks)
            if mask.sum() >= min_errors:
                corr[i] = err[mask].mean()
        c = g.copy()
        c["forecast"] = g["forecast"] - corr
        c["error"] = c["forecast"] - c["actual"]
        c["model"] = new_model
        out.append(c)
    return pd.concat(out, ignore_index=True) if out else eng.iloc[0:0]


def add_intervals(errors: pd.DataFrame, min_errors: int = INTERVAL_MIN_ERRORS,
                  quantiles: tuple[float, float] = INTERVAL_QUANTILES) -> pd.DataFrame:
    """Add lower/upper from the 5%/95% quantiles of the model's own past relative errors
    (actual / forecast - 1) at the same grain, series and horizon, and ``covered``."""
    out = errors.copy()
    out["lower"] = np.nan
    out["upper"] = np.nan
    for _, g in out.groupby(["grain", "series", "horizon", "model"]):
        g = g.sort_values("origin")
        origins = pd.to_datetime(g["origin"]).to_numpy()
        ends = pd.to_datetime(g["period_end"]).to_numpy()
        f = g["forecast"].to_numpy(dtype=float)
        a = g["actual"].to_numpy(dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            rel = np.where(f > 0, a / f - 1.0, np.nan)
        lo, hi = np.full(len(g), np.nan), np.full(len(g), np.nan)
        for i in range(len(g)):
            mask = _known_mask(origins, ends, i, None) & ~np.isnan(rel)
            if mask.sum() >= min_errors:
                ql, qh = np.quantile(rel[mask], quantiles)
                lo[i], hi[i] = f[i] * (1 + ql), f[i] * (1 + qh)
        out.loc[g.index, "lower"] = lo
        out.loc[g.index, "upper"] = hi
    has = out["lower"].notna() & (pd.to_datetime(out["origin"]).dt.date >= COVERAGE_FROM)
    inside = ((out["actual"] >= out["lower"]) & (out["actual"] <= out["upper"])).astype(float)
    out["covered"] = inside.where(has)
    return out
