"""Layer 3: scenarios "like last time" (step D).

1. **Episode library.** Past heat spells, droughts, abortion and mastitis surges are found
   in the herd-level daily aggregates; the labelled breaks (``episodes.BREAKS``) are added.
2. **Response.** For each episode, the forecasts made at its onset (first origin in the 7
   days from the start) are compared with what happened: the relative error at each
   horizon minus the model's usual error at that horizon in the year before the episode.
   What remains is how far the episode pushed milk (or a herd series) away from the
   forecast.
3. **Scenario.** A baseline forecast is multiplied by (1 + median response) for the
   chosen kind, with a range from the spread across episodes, and a plain sentence.

Responses come from a handful of episodes in one herd: they are associations, reported
with their number of episodes, never causes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import numpy as np
import pandas as pd

from .episodes import BREAKS

KIND_LABELS = {
    "heat": "heat spells", "drought": "dry spells", "abortion_surge": "abortion surges",
    "mastitis_surge": "mastitis surges", "herd contraction": "herd contractions",
}


@dataclass(frozen=True)
class EpisodeConfig:
    heat_anomaly: float = 3.0     # 14-day mean THI above the seasonal norm by this much
    heat_min_days: int = 14
    drought_quantile: float = 0.2  # 90-day rain below this seasonal quantile
    drought_min_days: int = 30
    surge_ratio: float = 2.0      # 28-day count at least this times the past-year median
    surge_min_count: float = 5.0  # ... and at least this many events in 28 days
    merge_days: int = 30
    clim_halfwidth: int = 15


def _runs(flag: pd.Series, min_days: int, merge_days: int) -> list[tuple]:
    """(start, end) of runs of True of at least ``min_days``, merging close runs."""
    runs, start, prev = [], None, None
    for d, v in flag.items():
        if v and start is None:
            start = d
        if not v and start is not None:
            runs.append((start, prev))
            start = None
        prev = d
    if start is not None:
        runs.append((start, prev))
    merged = []
    for s, e in runs:
        if merged and (s - merged[-1][1]).days <= merge_days:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    return [(s, e) for s, e in merged if (e - s).days + 1 >= min_days]


def _seasonal_norm(x: pd.Series, halfwidth: int, how: str = "mean", q: float = 0.5) -> pd.Series:
    doy = x.index.dayofyear.to_numpy().astype(float)
    vals = x.to_numpy()
    out = np.full(len(x), np.nan)
    for d in np.unique(doy):
        dist = np.abs(doy - d) % 365.25
        m = (np.minimum(dist, 365.25 - dist) <= halfwidth) & np.isfinite(vals)
        if m.sum() >= 20:
            out[doy == d] = np.mean(vals[m]) if how == "mean" else np.quantile(vals[m], q)
    return pd.Series(out, index=x.index)


def detect_episodes(daily: pd.DataFrame, cfg: EpisodeConfig = EpisodeConfig(),
                    breaks=BREAKS) -> pd.DataFrame:
    """Episode library: kind, start, end (labels of the past, from the full record)."""
    d = daily.copy()
    d.index = pd.to_datetime(d["date"])
    d = d.sort_index().reindex(pd.date_range(d.index.min(), d.index.max()))
    rows = []
    w = d["weather_is_complete"].astype("boolean").fillna(False).astype(bool)
    thi = d["thi_mean"].where(w)
    # Library labels describe the past, so centred windows (using days on both sides) are
    # fine and date the start correctly; trailing windows would date it about a week late.
    anom = (thi - _seasonal_norm(thi, cfg.clim_halfwidth)).rolling(14, min_periods=10, center=True).mean()
    for s, e in _runs(anom >= cfg.heat_anomaly, cfg.heat_min_days, cfg.merge_days):
        rows.append(("heat", s, e))
    rain90 = d["rain_total_mm"].where(w).rolling(90, min_periods=75, center=True).sum()
    low = _seasonal_norm(rain90, cfg.clim_halfwidth, how="q", q=cfg.drought_quantile)
    for s, e in _runs(rain90 < low, cfg.drought_min_days, cfg.merge_days):
        rows.append(("drought", s, e))
    for col, kind in (("real_abortions", "abortion_surge"), ("mastitis_episodes", "mastitis_surge")):
        if col not in d:
            continue
        c28 = d[col].rolling(28, min_periods=21, center=True).sum()
        base = c28.shift(42).rolling(365, min_periods=180).median()  # the year before the window
        surge = (c28 >= cfg.surge_ratio * base.clip(lower=1)) & (c28 >= cfg.surge_min_count)
        for s, e in _runs(surge.fillna(False), 14, cfg.merge_days):
            rows.append((kind, s, e))
    for b in breaks:
        if b.kind == "herd contraction":
            rows.append((b.kind, pd.Timestamp(b.start), pd.Timestamp(b.start) + pd.Timedelta(days=90)))
    out = pd.DataFrame(rows, columns=["kind", "start", "end"])
    out["start"] = pd.to_datetime(out["start"]).dt.date
    out["end"] = pd.to_datetime(out["end"]).dt.date
    return out.sort_values(["kind", "start"]).reset_index(drop=True)


def episode_response(errors: pd.DataFrame, episodes: pd.DataFrame, model: str,
                     series: str = "herd_milk", onset_days: int = 7,
                     baseline_days: int = 365, min_baseline: int = 8) -> pd.DataFrame:
    """Per episode x grain x horizon: excess relative error of forecasts made at onset."""
    e = errors[(errors["model"] == model) & (errors["series"] == series)].copy()
    e["origin"] = pd.to_datetime(e["origin"]).dt.date
    e["period_end"] = pd.to_datetime(e["period_end"]).dt.date
    e = e[(e["forecast"] > 0) & (e["actual"] > 0)]
    e["rel"] = e["actual"] / e["forecast"] - 1
    rows = []
    for ep in episodes.itertuples(index=False):
        onset = e[(e["origin"] >= ep.start) & (e["origin"] < ep.start + timedelta(days=onset_days))]
        for (grain, h), g in onset.groupby(["grain", "horizon"]):
            first = g.sort_values("origin").iloc[0]
            past = e[(e["grain"] == grain) & (e["horizon"] == h)
                     & (e["period_end"] <= ep.start)
                     & (e["origin"] >= ep.start - timedelta(days=baseline_days))]
            if len(past) < min_baseline:
                continue
            rows.append(dict(kind=ep.kind, start=ep.start, grain=grain, horizon=int(h),
                             response=float(first["rel"] - past["rel"].median()),
                             n_baseline=len(past)))
    return pd.DataFrame(rows, columns=["kind", "start", "grain", "horizon", "response", "n_baseline"])


def summarize_response(resp: pd.DataFrame) -> pd.DataFrame:
    """Per kind x grain x horizon: n episodes, median response and its spread."""
    if not len(resp):
        return pd.DataFrame(columns=["kind", "grain", "horizon", "n", "median", "low", "high"])
    g = resp.groupby(["kind", "grain", "horizon"])["response"]
    out = g.agg(n="count", median="median").reset_index()
    lo = g.quantile(0.1).to_numpy()
    hi = g.quantile(0.9).to_numpy()
    small = out["n"].to_numpy() < 5   # with few episodes show the full range
    out["low"] = np.where(small, g.min().to_numpy(), lo)
    out["high"] = np.where(small, g.max().to_numpy(), hi)
    return out


def apply_scenario(baseline: pd.DataFrame, summary: pd.DataFrame, kind: str) -> pd.DataFrame:
    """Baseline rows (grain, horizon, forecast, ...) with scenario forecast and range."""
    s = summary[summary["kind"] == kind][["grain", "horizon", "n", "median", "low", "high"]]
    out = baseline.merge(s, on=["grain", "horizon"], how="left")
    # horizons between measured ones are interpolated; none beyond the measured range
    for grain, g in s.groupby("grain"):
        g = g.sort_values("horizon")
        h = g["horizon"].to_numpy(dtype=float)
        m = (out["grain"] == grain) & out["median"].isna() & out["horizon"].between(h.min(), h.max())
        for col in ("median", "low", "high"):
            out.loc[m, col] = np.interp(out.loc[m, "horizon"].astype(float), h, g[col].to_numpy())
        out.loc[m, "n"] = int(g["n"].min())
    out["scenario"] = kind
    out["scenario_forecast"] = out["forecast"] * (1 + out["median"])
    out["scenario_low"] = out["forecast"] * (1 + out["low"])
    out["scenario_high"] = out["forecast"] * (1 + out["high"])
    return out


def narrative(summary: pd.DataFrame, kind: str, grain: str, horizon: int,
              series_label: str = "herd milk") -> str:
    row = summary[(summary["kind"] == kind) & (summary["grain"] == grain)
                  & (summary["horizon"] == horizon)]
    label = KIND_LABELS.get(kind, kind)
    unit = {"weekly": "week", "monthly": "month", "daily": "day"}.get(grain, grain)
    if not len(row):
        return f"No earlier {label} with usable forecasts, so no scenario for {horizon} {unit}(s) ahead."
    r = row.iloc[0]
    direction = "below" if r["median"] < 0 else "above"
    return (f"In the {int(r['n'])} earlier {label}, {series_label} {horizon} {unit}"
            f"{'s' if horizon != 1 else ''} after the start was {abs(r['median']):.0%} {direction} "
            f"the forecast (range {r['low']:+.0%} to {r['high']:+.0%}). "
            f"This is what happened before, not a proven cause.")
