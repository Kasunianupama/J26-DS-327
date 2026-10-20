"""Honest prediction intervals (H3): adaptive conformal inference with record-quality scaling.

pfoi-1.0.0 took the 5 % / 95 % quantiles of all past relative errors. Its 90 % intervals
covered 34-83 % in development, because errors grow after breaks and in poor-record
periods while old calm errors keep the quantiles narrow. Here, per series x grain x
horizon x model, using only errors whose target period ended before the origin:

1. residuals are log(actual / forecast);
2. **recency weights** 0.5 ** (age / half-life) let the spread follow the current regime;
3. **record quality**: each residual is divided by the spread factor of the quality band
   at its own origin (band of the 28 days before the origin, known at the time), and the
   new interval is multiplied by the factor of the current band. Factors are learned from
   the finished errors (band spread / normal spread, at least 1), with defaults while a
   band has too few errors;
4. **adaptive conformal inference** (Gibbs & Candes 2021): every finished forecast whose
   issued interval missed lowers the miscoverage level used next (wider), every hit
   raises it slightly, so long-run coverage holds at the target under drift.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from .episodes import DEGRADED, GAP, NORMAL, UNVERIFIED, period_band
from .error_tools import COVERAGE_FROM

LEVELS = {80: 0.20, 90: 0.10}
DEFAULT_FACTORS = {NORMAL: 1.0, DEGRADED: 1.5, UNVERIFIED: 2.0, GAP: 2.0}
ORIGIN_WINDOW_DAYS = 28


def origin_bands(origins, quality: pd.DataFrame, days: int = ORIGIN_WINDOW_DAYS) -> dict:
    """Band of the ``days`` before each origin (known at the origin)."""
    out = {}
    for o in set(origins):
        o = pd.Timestamp(o).date()
        out[o] = period_band(quality, o - timedelta(days=days), o)
    return out


def weighted_quantile(x: np.ndarray, w: np.ndarray, q: float) -> float:
    order = np.argsort(x)
    x, w = x[order], w[order]
    c = (np.cumsum(w) - 0.5 * w) / w.sum()
    return float(np.interp(q, c, x))


def _mad(x: np.ndarray) -> float:
    if len(x) < 2:
        return np.nan
    return float(1.4826 * np.median(np.abs(x - np.median(x))))


def _band_factors(r: np.ndarray, bands: np.ndarray, band_min: int) -> dict:
    normal = r[bands == NORMAL]
    base = _mad(normal) if len(normal) >= band_min else _mad(r)
    out = dict(DEFAULT_FACTORS)
    if not np.isfinite(base) or base <= 0:
        return out
    for b in (DEGRADED, UNVERIFIED, GAP):
        rb = r[bands == b]
        if len(rb) >= band_min:
            s = _mad(rb)
            if np.isfinite(s):
                out[b] = max(1.0, s / base)
    return out


def aci_intervals(errors: pd.DataFrame, band_at_origin: dict | None = None,
                  levels: dict = LEVELS, half_life_days: float = 365.0, gamma: float = 0.02,
                  min_errors: int = 12, band_min: int = 12,
                  coverage_from: date = COVERAGE_FROM) -> pd.DataFrame:
    """``errors`` plus lower{L}/upper{L}/covered{L} for each level L, and ``origin_band``."""
    out = errors.reset_index(drop=True).copy()
    for col in ("origin", "period_end"):
        out[col] = pd.to_datetime(out[col]).dt.date
    out["origin_band"] = [(band_at_origin or {}).get(o, NORMAL) for o in out["origin"]]
    for lv in levels:
        out[f"lower{lv}"] = np.nan
        out[f"upper{lv}"] = np.nan
    for _, g in out.groupby(["grain", "series", "horizon", "model"], sort=False):
        idx = g.index.to_numpy()
        o = pd.to_datetime(g["origin"]).to_numpy()
        e = pd.to_datetime(g["period_end"]).to_numpy()
        f = g["forecast"].to_numpy(dtype=float)
        a = g["actual"].to_numpy(dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            r = np.where((f > 0) & (a > 0), np.log(a / f), np.nan)
        bands = g["origin_band"].to_numpy()
        by_end = np.argsort(e, kind="stable")
        alpha = dict(levels)
        bounds = {lv: (np.full(len(g), np.nan), np.full(len(g), np.nan)) for lv in levels}
        issued: dict[int, dict] = {}
        done = 0
        for u in np.unique(o):
            while done < len(by_end) and e[by_end[done]] <= u:
                j = by_end[done]
                done += 1
                if j in issued and np.isfinite(r[j]):
                    for lv, target in levels.items():
                        lo, hi = issued[j][lv]
                        miss = float(not (lo <= r[j] <= hi))
                        alpha[lv] = float(np.clip(alpha[lv] + gamma * (target - miss), 0.005, 0.5))
            fin = by_end[:done]
            fin = fin[np.isfinite(r[fin])]
            if len(fin) < min_errors:
                continue
            fac = _band_factors(r[fin], bands[fin], band_min)
            z = r[fin] / np.array([fac.get(b, 1.0) for b in bands[fin]])
            age = (u - e[fin]) / np.timedelta64(1, "D")
            w = 0.5 ** (age / half_life_days)
            rows = np.where(o == u)[0]
            for k in rows:
                scale = fac.get(bands[k], 1.0)
                issued[k] = {}
                for lv in levels:
                    lo = weighted_quantile(z, w, alpha[lv] / 2) * scale
                    hi = weighted_quantile(z, w, 1 - alpha[lv] / 2) * scale
                    issued[k][lv] = (lo, hi)
                    bounds[lv][0][k] = f[k] * np.exp(lo)
                    bounds[lv][1][k] = f[k] * np.exp(hi)
        for lv, (lo_arr, hi_arr) in bounds.items():
            out.loc[idx, f"lower{lv}"] = lo_arr
            out.loc[idx, f"upper{lv}"] = hi_arr
    scored = out["origin"].map(lambda d: d >= coverage_from)
    for lv in levels:
        has = out[f"lower{lv}"].notna() & scored
        inside = ((out["actual"] >= out[f"lower{lv}"]) & (out["actual"] <= out[f"upper{lv}"])).astype(float)
        out[f"covered{lv}"] = inside.where(has)
    return out


# --------------------------------------------------------------------------- M4: staleness
# docs/pp1_plan.md M4: ranges widen as trusted milk records get older. The scale is
# measured, not assumed: the spread of the milk baseline's log errors by days since the last
# trusted milk day, from the simulated outages of the development block (outage_sim,
# ``outage_staleness_*.csv``). Without that file no widening is applied and the run says so.

STALE_MIN_N = 12
FRESH_BAND = 0  # band starting at 0 days (the last trusted day is yesterday or today)


class StalenessScale:
    """Spread multiplier by days since the last trusted milk day, per grain and horizon."""

    def __init__(self, table: pd.DataFrame | None, source: str = "not measured"):
        self.source = source if table is not None and len(table) else "not measured"
        self.rows: dict[tuple[str, int], list[tuple[float, float]]] = {}
        if table is None or not len(table):
            return
        t = table.copy()
        t["lo"] = t["stale_band"].astype(str).str.extract(r"\[?\(?\s*([0-9.]+)")[0].astype(float)
        for (grain, h), g in t.groupby(["grain", "horizon"]):
            g = g.sort_values("lo")
            fresh = g[(g["lo"] == FRESH_BAND) & (g["n"] >= STALE_MIN_N)]
            if not len(fresh) or not fresh["sd"].iloc[0] > 0:
                continue
            base, factor, steps = float(fresh["sd"].iloc[0]), 1.0, []
            for r in g.itertuples():
                if r.n >= STALE_MIN_N and np.isfinite(r.sd):
                    factor = max(factor, float(r.sd) / base)  # never narrower when staler
                steps.append((float(r.lo), factor))
            self.rows[(str(grain), int(h))] = steps

    @classmethod
    def from_csv(cls, path) -> "StalenessScale":
        from pathlib import Path

        p = Path(path) if path else None
        if p is None or not p.exists():
            return cls(None)
        return cls(pd.read_csv(p), source=f"measured: {p.name}")

    def factor(self, grain: str, horizon: int, stale_days: float) -> float:
        """Multiplier (>= 1) for this staleness; 1 when not measured."""
        if not np.isfinite(stale_days) or not self.rows:
            return 1.0
        keys = [k for k in self.rows if k[0] == grain]
        if not keys:
            return 1.0
        above = sorted(k for k in keys if k[1] >= horizon)
        key = above[0] if above else max(keys, key=lambda k: k[1])
        out = 1.0
        for lo, f in self.rows[key]:
            if stale_days >= lo:
                out = f
        return out


def widen_relative(q_lo: float, q_hi: float, factor: float) -> tuple[float, float]:
    """Scale a relative range (actual / forecast - 1) by ``factor`` in log space."""
    lo = np.expm1(np.log1p(max(q_lo, -0.999)) * factor)
    hi = np.expm1(np.log1p(q_hi) * factor)
    return float(lo), float(hi)


def aci_interval_next(errors: pd.DataFrame, origin: date, quality: pd.DataFrame | None = None,
                      level: int = 90, **kw) -> pd.DataFrame:
    """ACI range for a forecast issued at ``origin``, per (model, grain, series, horizon),
    as relative quantiles ``q_lo`` / ``q_hi`` (same columns as ``outlook.interval_table``).

    Uses only errors whose target period ended by ``origin``; the record-quality band of
    the 28 days before ``origin`` scales the range when ``quality`` is given."""
    cols = ["model", "grain", "series", "horizon", "q_lo", "q_hi", "n"]
    if errors is None or not len(errors):
        return pd.DataFrame(columns=cols)
    e = errors.copy()
    for c in ("origin", "period_end"):
        e[c] = pd.to_datetime(e[c]).dt.date
    e = e[(e["period_end"] <= origin) & (e["origin"] < origin)]
    if not len(e):
        return pd.DataFrame(columns=cols)
    keys = ["model", "grain", "series", "horizon"]
    probe = e.groupby(keys, as_index=False).size().drop(columns="size")
    probe = probe.assign(origin=origin, period_end=origin + timedelta(days=4000),
                         forecast=1.0, actual=np.nan, _probe=True)
    work = pd.concat([e.assign(_probe=False), probe], ignore_index=True)
    bands = origin_bands(work["origin"], quality) if quality is not None else None
    res = aci_intervals(work, band_at_origin=bands, levels={level: LEVELS[level]}, **kw)
    p = res[res["_probe"].astype(bool) & res[f"lower{level}"].notna()]
    n = e.groupby(keys).size().rename("n").reset_index()
    out = p[keys].assign(q_lo=p[f"lower{level}"].to_numpy() - 1.0,
                         q_hi=p[f"upper{level}"].to_numpy() - 1.0).merge(n, on=keys)
    return out[cols].reset_index(drop=True)
