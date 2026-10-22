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

Optional damped local linear trend (``TrendConfig``, pfoi-1.2.1-dev): the level gets a
slope that is damped by ``phi`` per 30 days and fed by its own noise ``q_trend``. Each
forecast is corrected by the level at its origin plus the damped slope carried from the
origin to the end of its target period, so a steady drift in the error (e.g. yield per cow
falling for two years) is followed instead of held flat. ``phi`` = 0 (or no trend) gives
the plain level exactly; ``phi`` = 1 (an undamped trend) is not allowed.

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


@dataclass(frozen=True)
class TrendConfig:
    """Damped trend on the adaptive level. Kept apart from ``AdaptiveConfig`` so the frozen
    pfoi-1.0.0 / 1.1.0 configuration hashes do not change."""
    phi: float = 0.9             # slope damping per 30 days, 0 <= phi < 1 (0 = no trend)
    q_trend: float = 0.05        # slope variance added per 30 days, as a share of noise variance

    def __post_init__(self):
        if not 0.0 <= self.phi < 1.0:
            raise ValueError("trend damping phi must be in [0, 1); phi = 1 is not allowed")
        if self.q_trend < 0:
            raise ValueError("q_trend must be >= 0")

    @property
    def off(self) -> bool:
        return self.phi == 0.0

    def label(self) -> str:
        return f"d{self.phi:g}b{self.q_trend:g}"


def damped_gain(days: float, phi: float) -> float:
    """Sum of the damped slope over ``days`` (slope per 30 days): phi + phi^2 + ... + phi^m,
    m = days / 30, continuous in m. 0 when phi = 0."""
    if phi == 0.0 or days <= 0:
        return 0.0
    return phi * (1.0 - phi ** (days / 30.0)) / (1.0 - phi)


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


def level_trend_at(ends: np.ndarray, y: np.ndarray, hz: np.ndarray, origin: np.datetime64,
                   cfg: AdaptiveConfig, trend: TrendConfig,
                   keep: np.ndarray | None = None) -> tuple[float, float]:
    """(level, slope per 30 days) at ``origin`` from finished errors (end <= origin), with a
    damped local linear trend. Same filter as ``level_at`` (time-scaled drift, fading,
    break reset, per-horizon noise) plus the slope state; with ``phi`` = 0 the level equals
    ``level_at`` exactly and the slope is 0."""
    known = (ends <= origin) & ~np.isnan(y)
    if keep is not None:
        known &= keep
    if known.sum() < cfg.min_obs:
        return 0.0, 0.0
    e, v, h = ends[known], y[known], hz[known]
    order = np.lexsort((h, e))
    e, v, h = e[order], v[order], h[order]
    pooled_r = _robust_var(v)
    if not np.isfinite(pooled_r) or pooled_r <= 0:
        return 0.0, 0.0
    r_by_h = {}
    for hh in np.unique(h):
        vv = v[h == hh]
        r = _robust_var(vv) if len(vv) >= 3 else np.nan
        r_by_h[hh] = r if np.isfinite(r) and r > 0 else pooled_r
    phi = trend.phi
    q = cfg.q30 * pooled_r / 30.0
    qb = trend.q_trend * pooled_r / 30.0 if phi else 0.0
    p0 = pooled_r
    pb0 = trend.q_trend * pooled_r if phi else 0.0
    x, b = 0.0, 0.0
    pxx, pxb, pbb = p0, 0.0, pb0
    t_prev = e[0]
    shocks = 0

    def predict(dt: float) -> None:
        nonlocal x, b, pxx, pxb, pbb
        if cfg.tau_days:
            x *= np.exp(-dt / cfg.tau_days)
        if phi:
            d = phi ** (dt / 30.0)
            g = damped_gain(dt, phi)
            x += g * b
            b *= d
            pxx += 2 * g * pxb + g * g * pbb
            pxb = d * pxb + g * d * pbb
            pbb = d * d * pbb + qb * dt
        pxx += q * dt

    for ti, vi, hi in zip(e, v, h):
        dt = float((ti - t_prev) / np.timedelta64(1, "D"))
        if dt > 0:
            predict(dt)
        r = r_by_h[hi]
        s = pxx + r
        innov = vi - x
        if abs(innov) / np.sqrt(s) > cfg.z_reset:
            shocks += 1
            if shocks >= 2:
                pxx = max(pxx, p0)
                pbb = max(pbb, pb0)
                s = pxx + r
        else:
            shocks = 0
        kx, kb = pxx / s, pxb / s
        x += kx * innov
        b += kb * innov
        pbb = pbb - kb * pxb
        pxb = (1 - kx) * pxb
        pxx = (1 - kx) * pxx
        t_prev = ti
    dt = max(float((origin - t_prev) / np.timedelta64(1, "D")), 0.0)
    if cfg.tau_days:
        x *= np.exp(-dt / cfg.tau_days)
    if phi:
        x += damped_gain(dt, phi) * b
        b *= phi ** (dt / 30.0)
    return float(x), float(b)


def adaptive_corrected(errors: pd.DataFrame, base_model: str, new_model: str | None = None,
                       cfg: AdaptiveConfig = AdaptiveConfig(), breaks: list | None = None,
                       trend: TrendConfig | None = None) -> pd.DataFrame:
    """Rows of ``base_model`` with forecasts multiplied by (1 + level at their origin).

    With ``trend`` (phi > 0) the factor is 1 + level + damped slope carried from the origin
    to the end of the row's target period, clipped like the errors. ``trend`` off or
    phi = 0 is exactly the plain level correction."""
    use_trend = trend is not None and not trend.off
    new_model = new_model or (f"{base_model}_adaptive_trend" if use_trend else f"{base_model}_adaptive")
    if use_trend:
        return _trend_corrected(errors, base_model, new_model, cfg, breaks, trend)
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


def _trend_corrected(errors: pd.DataFrame, base_model: str, new_model: str, cfg: AdaptiveConfig,
                     breaks: list | None, trend: TrendConfig) -> pd.DataFrame:
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
        states = {}
        for o in np.unique(origins):
            keep = None
            if breaks:
                from .breaks import since_mask
                keep = since_mask(origins, o, breaks)
            states[o] = level_trend_at(ends, y, hz, o, cfg, trend, keep=keep)
        lead = (ends - origins) / np.timedelta64(1, "D")
        corr = np.array([states[o][0] + states[o][1] * damped_gain(float(d), trend.phi)
                         for o, d in zip(origins, lead)])
        c = g.copy()
        c["forecast"] = f * (1 + np.clip(corr, *Y_CLIP))
        c["error"] = c["forecast"] - c["actual"]
        c["model"] = new_model
        out.append(c)
    return pd.concat(out, ignore_index=True) if out else base.iloc[0:0]
