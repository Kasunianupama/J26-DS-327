"""Layer 1: adaptive level correction of a model's forecasts (H4).

The structural forecast is kept and multiplied by (1 + x), where x is the current level of
the model's relative error (actual / forecast - 1), tracked by a local-level Kalman filter
over the errors whose target period had **ended by the origin** (nothing later is used):

* time-scaled drift: between two finished errors the level's variance grows by
  ``q30`` x (typical error variance) per 30 days, so after a long data gap the first new
  errors move the level quickly;
* optional mean reversion: with ``tau_days`` the level decays towards 0 over time, so a
  correction learned before a gap fades if nothing confirms it;
* break response: two successive errors more than ``z_reset`` standard deviations from
  the level reset its variance, so a regime change is picked up within weeks;
* ``pooled``: errors of every horizon of the same series inform one level (each with its
  own noise variance), so the newest short-horizon errors also correct long horizons.

This generalises ``error_tools.bias_corrected`` (a fixed 2-year mean of past errors).
Error tables have the backtest columns (origin, grain, horizon, period_end, series,
model, forecast, actual, ...).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

MIN_OBS = 6
Y_CLIP = (-0.9, 3.0)


@dataclass(frozen=True)
class AdaptiveConfig:
    q30: float = 0.1             # level variance added per 30 days, as a share of noise variance
    tau_days: float | None = 365.0  # mean reversion of the level towards 0 (None = none)
    z_reset: float = 3.0         # |innovation| / sd that counts as a shock
    pooled: bool = True          # one level per series across horizons
    min_obs: int = MIN_OBS

    def label(self) -> str:
        tau = "n" if self.tau_days is None else f"{int(self.tau_days)}"
        return f"{'p' if self.pooled else 'h'}q{self.q30:g}t{tau}z{self.z_reset:g}"


def _robust_var(y: np.ndarray) -> float:
    if len(y) < 2:
        return np.nan
    mad = np.median(np.abs(y - np.median(y)))
    v = (1.4826 * mad) ** 2
    return float(v if v > 0 else np.var(y))


def level_at(ends: np.ndarray, y: np.ndarray, hz: np.ndarray, origin: np.datetime64,
             cfg: AdaptiveConfig, keep: np.ndarray | None = None) -> float:
    """Filtered error level at ``origin`` from finished errors (end <= origin).
    ``keep``: optional mask of usable errors (e.g. only those after the latest break)."""
    known = (ends <= origin) & ~np.isnan(y)
    if keep is not None:
        known &= keep
    if known.sum() < cfg.min_obs:
        return 0.0
    e, v, h = ends[known], y[known], hz[known]
    order = np.lexsort((h, e))
    e, v, h = e[order], v[order], h[order]
    pooled_r = _robust_var(v)
    if not np.isfinite(pooled_r) or pooled_r <= 0:
        return 0.0
    r_by_h = {}
    for hh in np.unique(h):
        vv = v[h == hh]
        r = _robust_var(vv) if len(vv) >= 3 else np.nan
        r_by_h[hh] = r if np.isfinite(r) and r > 0 else pooled_r
    q = cfg.q30 * pooled_r / 30.0
    p0 = pooled_r
    x, p = 0.0, p0
    t_prev = e[0]
    shocks = 0
    for ti, vi, hi in zip(e, v, h):
        dt = float((ti - t_prev) / np.timedelta64(1, "D"))
        if dt > 0:
            if cfg.tau_days:
                x *= np.exp(-dt / cfg.tau_days)
            p += q * dt
        r = r_by_h[hi]
        s = p + r
        innov = vi - x
        if abs(innov) / np.sqrt(s) > cfg.z_reset:
            shocks += 1
            if shocks >= 2:
                p = max(p, p0)
                s = p + r
        else:
            shocks = 0
        k = p / s
        x += k * innov
        p = (1 - k) * p
        t_prev = ti
    if cfg.tau_days:
        dt = float((origin - t_prev) / np.timedelta64(1, "D"))
        x *= np.exp(-max(dt, 0.0) / cfg.tau_days)
    return float(x)


def adaptive_corrected(errors: pd.DataFrame, base_model: str, new_model: str | None = None,
                       cfg: AdaptiveConfig = AdaptiveConfig(), breaks: list | None = None) -> pd.DataFrame:
    """Rows of ``base_model`` with forecasts multiplied by (1 + level at their origin)."""
    new_model = new_model or f"{base_model}_adaptive"
    base = errors[errors["model"] == base_model]
    out = []
    keys = ["grain", "series"] if cfg.pooled else ["grain", "series", "horizon"]
    for _, g in base.groupby(keys):
        g = g.sort_values("origin")
        origins = pd.to_datetime(g["origin"]).to_numpy()
        ends = pd.to_datetime(g["period_end"]).to_numpy()
        f = g["forecast"].to_numpy(dtype=float)
        a = g["actual"].to_numpy(dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            y = np.where(f > 0, np.clip(a / f - 1.0, *Y_CLIP), np.nan)
        hz = g["horizon"].to_numpy(dtype=int)
        if breaks:  # PP1 1a: only errors from forecast dates after the latest known break
            from .breaks import since_mask
            levels = {o: level_at(ends, y, hz, o, cfg, keep=since_mask(origins, o, breaks))
                      for o in np.unique(origins)}
        else:
            levels = {o: level_at(ends, y, hz, o, cfg) for o in np.unique(origins)}
        c = g.copy()
        c["forecast"] = f * (1 + np.array([levels[o] for o in origins]))
        c["error"] = c["forecast"] - c["actual"]
        c["model"] = new_model
        out.append(c)
    return pd.concat(out, ignore_index=True) if out else base.iloc[0:0]
