"""Specialists after the stability gate (G2; docs/stability_gate.md).

G1 (user run 2026-10-22) found the gate recognises unstable regimes at short and medium horizons
but not at week 13 or months 6-12, where 1.2.0-dev misses most of the time anyway. So:

**Track A, short and medium horizons (day 1-14, week 1-8, month 1-3), gated.**
S1 ``s1_relevel``: the raw structural forecast (``milk_baseline``, engine x curve x k) re-levelled
by the mean log error of its own finished short forecasts (lead at most 14 days) whose period
ended in the 14 days before the origin, trusted periods only. Same structure, much faster memory
than the Kalman level of 1.2.0-dev; it is not persistence (the engine's cow path and curve stay).
``gated_s1`` uses S1 only where the logistic gate (G1, fitted on earlier years) says unstable
(p > 0.5) and only in Track A cells; everywhere else it is 1.2.0-dev unchanged.

**Track B, long horizons, every period (no gate).** A zero-shot pretrained forecaster, Chronos-2
(Apache-2.0, run locally), forecasts weekly litres per recorded milking cow from trusted days of
the current milk source before the origin; the forecast is that yield times the herd engine's
projected mean milking cows of the target period (``chronos2_ypc_x_engine``). A direct Chronos-2
forecast of herd litres per day (``chronos2_milk``) is reported beside it. Nothing is fitted on
Farm X, so no fold structure is needed; missing weeks stay missing (the model masks NaN).

Keep rules (fixed 2026-10-22, before any real-data run), on trusted periods, share within +-10 %:

* Track A (fold years 2019-2023, the periods the G1 gate scored): the mean over Track A cells rises
  by at least 2 points, no Track A cell falls by more than 1 point, and 2019 (stable) falls by at
  most 1 point.
* Track B (development origins 2017-2023, periods matched with 1.2.0-dev): the share rises at
  week 13, month 6 and month 12, and no development year falls by more than 5 points (a year's
  share = mean over those three cells).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable

import numpy as np
import pandas as pd

from .episodes import VERIFIED_BANDS
from .gate import EXCLUDED_ALTERNATIVES, KEYS, MISS_TOL, daily_signals

TRACK_A_CELLS = (("daily", 1), ("daily", 7), ("daily", 14), ("weekly", 1), ("weekly", 4),
                 ("weekly", 8), ("monthly", 1), ("monthly", 3))
TRACK_B_CELLS = (("weekly", 13), ("monthly", 6), ("monthly", 12))
A_MIN_MEAN_RISE = 0.02
A_MAX_CELL_FALL = 0.01
A_STABLE_YEAR, A_MAX_STABLE_FALL = 2019, 0.01
B_MAX_YEAR_FALL = 0.05
DEV_START, DEV_END = date(2017, 1, 1), date(2024, 1, 1)


def _keyed(rows: pd.DataFrame) -> pd.DataFrame:
    r = rows.copy()
    for c in ("origin", "period_start", "period_end"):
        if c in r:
            r[c] = pd.to_datetime(r[c]).dt.date
    r["horizon"] = r["horizon"].astype(int)
    return r


# --------------------------------------------------------------------------- Track A

def fast_relevel(errors: pd.DataFrame, raw_model: str = "milk_baseline", window_days: int = 14,
                 max_lead_days: int = 14, min_errors: int = 2, max_log: float = np.log(2.0),
                 new_model: str = "s1_relevel") -> pd.DataFrame:
    """S1: raw forecast x exp(level), level = mean log(actual / forecast) of the raw model's
    finished forecasts with lead <= ``max_lead_days`` whose period ended within ``window_days``
    before the origin (trusted bands only, when bands are present). Fewer than ``min_errors`` such
    errors: no S1 forecast at that origin."""
    raw = _keyed(errors[errors["model"] == raw_model])
    if "series" in raw:
        raw = raw[raw["series"] == "herd_milk"]
    lead = np.array([(e - o).days for o, e in zip(raw["origin"], raw["period_end"])])
    ok = (lead <= max_lead_days) & (raw["actual"] > 0).to_numpy() & (raw["forecast"] > 0).to_numpy()
    if "band" in raw:
        ok &= raw["band"].isin(VERIFIED_BANDS).to_numpy()
    src = raw[ok]
    ends = pd.to_datetime(src["period_end"]).to_numpy()
    y = np.log(src["actual"].to_numpy() / src["forecast"].to_numpy())
    level = {}
    for o in sorted(set(raw["origin"])):
        t = np.datetime64(pd.Timestamp(o))
        m = (ends <= t) & (ends > t - np.timedelta64(window_days, "D"))
        level[o] = float(np.clip(y[m].mean(), -max_log, max_log)) if m.sum() >= min_errors else np.nan
    out = raw.copy()
    lv = out["origin"].map(level).to_numpy(dtype=float)
    out["forecast"] = out["forecast"].to_numpy() * np.exp(lv)
    out = out[np.isfinite(lv)].copy()
    out["error"] = out["forecast"] - out["actual"]
    out["model"] = new_model
    return out.reset_index(drop=True)


def gated_switch(base: pd.DataFrame, specialist: pd.DataFrame, probs: pd.DataFrame,
                 gate: str = "logistic", threshold: float = 0.5, cells=TRACK_A_CELLS,
                 new_model: str = "gated_s1") -> pd.DataFrame:
    """Base rows, replaced by the specialist where the gate's probability exceeds ``threshold``,
    the cell is one of ``cells`` and the specialist has a forecast. Adds ``switched``."""
    if set(specialist["model"]) & set(EXCLUDED_ALTERNATIVES):
        raise ValueError("persistence is never a specialist")
    b = _keyed(base).drop_duplicates(KEYS).set_index(KEYS)
    s = _keyed(specialist).drop_duplicates(KEYS).set_index(KEYS)["forecast"]
    p = _keyed(probs).drop_duplicates(KEYS).set_index(KEYS)[f"p_{gate}"]
    cell_ok = np.array([(g, int(h)) in set(cells) for g, h, *_ in b.index])
    flag = p.reindex(b.index).to_numpy(dtype=float) > threshold
    has = s.reindex(b.index).notna().to_numpy()
    use = cell_ok & flag & has
    out = b.copy()
    out.loc[use, "forecast"] = s.reindex(b.index)[use].to_numpy()
    out["switched"] = use
    out["error"] = out["forecast"] - out["actual"]
    out["model"] = new_model
    return out.reset_index()


def _within(rows: pd.DataFrame) -> pd.Series:
    return (rows["forecast"] - rows["actual"]).abs() / rows["actual"] <= MISS_TOL + 1e-9


def matched_hits(frames: dict[str, pd.DataFrame], keys_from: pd.DataFrame | None = None,
                 by_year: bool = False) -> pd.DataFrame:
    """Share within +-10 % per model x grain x horizon (x forecast year), on the periods every
    model forecast (and, if given, only on the keys of ``keys_from``)."""
    parts = {m: _keyed(f).drop_duplicates(KEYS).set_index(KEYS) for m, f in frames.items()}
    common = None
    for f in parts.values():
        common = f.index if common is None else common.intersection(f.index)
    if keys_from is not None:
        common = common.intersection(_keyed(keys_from).drop_duplicates(KEYS).set_index(KEYS).index)
    rows = []
    for m, f in parts.items():
        g = f.loc[common].reset_index()
        g = g[g["actual"] > 0]
        g["hit"] = _within(g)
        g["year"] = pd.to_datetime(g["origin"]).dt.year
        keys = ["grain", "horizon"] + (["year"] if by_year else [])
        for k, c in g.groupby(keys):
            rows.append(dict(zip(keys, k), model=m, n=len(c), within_10=float(c["hit"].mean())))
    return pd.DataFrame(rows)


def track_a_rule(hits: pd.DataFrame, hits_y: pd.DataFrame, base: str, new: str):
    """Pre-registered Track A rule. Returns (checks table, keep)."""
    cells = set(TRACK_A_CELLS)
    h = hits[[(g, int(x)) in cells for g, x in zip(hits["grain"], hits["horizon"])]]
    piv = h.pivot_table(index=["grain", "horizon"], columns="model", values="within_10")
    diff = piv[new] - piv[base]
    hy = hits_y[[(g, int(x)) in cells for g, x in zip(hits_y["grain"], hits_y["horizon"])]]
    stable = hy[hy["year"] == A_STABLE_YEAR].groupby("model")["within_10"].mean()
    stable_change = float(stable.get(new, np.nan) - stable.get(base, np.nan))
    checks = pd.DataFrame([
        dict(check=f"mean over Track A cells rises >= {A_MIN_MEAN_RISE:.2f}", value=float(diff.mean()),
             passed=bool(diff.mean() >= A_MIN_MEAN_RISE)),
        dict(check=f"no Track A cell falls > {A_MAX_CELL_FALL:.2f}", value=float(diff.min()),
             passed=bool(diff.min() >= -A_MAX_CELL_FALL - 1e-12)),
        dict(check=f"{A_STABLE_YEAR} (stable) falls <= {A_MAX_STABLE_FALL:.2f}", value=stable_change,
             passed=bool(np.isfinite(stable_change) and stable_change >= -A_MAX_STABLE_FALL - 1e-12)),
    ])
    return checks, bool(checks["passed"].all())


def track_b_rule(hits: pd.DataFrame, hits_y: pd.DataFrame, base: str, new: str):
    """Pre-registered Track B rule. Returns (checks table, keep)."""
    rows = []
    for g, h in TRACK_B_CELLS:
        c = hits[(hits["grain"] == g) & (hits["horizon"] == h)].set_index("model")["within_10"]
        v = float(c.get(new, np.nan) - c.get(base, np.nan))
        rows.append(dict(check=f"{g} {h} rises", value=v, passed=bool(np.isfinite(v) and v > 0)))
    cells = set(TRACK_B_CELLS)
    hy = hits_y[[(g, int(x)) in cells for g, x in zip(hits_y["grain"], hits_y["horizon"])]]
    yr = hy.groupby(["year", "model"])["within_10"].mean().unstack()
    worst = float((yr[new] - yr[base]).min()) if new in yr and base in yr and len(yr) else np.nan
    rows.append(dict(check=f"no year falls > {B_MAX_YEAR_FALL:.2f} (mean of the three cells)", value=worst,
                     passed=bool(np.isfinite(worst) and worst >= -B_MAX_YEAR_FALL - 1e-12)))
    checks = pd.DataFrame(rows)
    return checks, bool(checks["passed"].all())


# --------------------------------------------------------------------------- Track B

def weekly_series(daily: pd.DataFrame) -> pd.DataFrame:
    """Weeks starting Monday: mean litres per recorded milking cow and mean herd litres per day on
    trusted days (at least 4 of 7, else missing), and the week's milk source (missing if mixed)."""
    sig = daily_signals(daily)
    litres = pd.to_numeric(daily.set_index(pd.to_datetime(daily["date"]))["target_litres"],
                           errors="coerce").reindex(sig.index)
    sig = sig.assign(ypc=np.exp(sig["log_ypc"]), litres=litres.where(sig["trusted"]))
    week = sig.index - pd.to_timedelta(sig.index.weekday, unit="D")
    g = sig.groupby(week)
    n = g["trusted"].sum()
    src = g["source"].agg(lambda s: s.dropna().iloc[0] if s.dropna().nunique() == 1 else None)
    out = pd.DataFrame({"ypc": g["ypc"].mean().where(n >= 4), "litres": g["litres"].mean().where(n >= 4),
                        "source": src, "n_trusted": n})
    out.index.name = "week"
    return out


def contexts(weekly: pd.DataFrame, origin: date, column: str, min_weeks: int = 26,
             max_weeks: int = 520, mode: str = "current") -> tuple[np.ndarray, pd.Timestamp] | None:
    """Context for an origin: weeks that ended before it (Monday start + 6 <= origin - 1), from the
    current source only (the source of the latest such week that has one; ``mode="all"`` keeps every
    source); NaN weeks, and weeks that mix two sources, are kept as missing. ``None`` when fewer than
    ``min_weeks`` known weeks."""
    o = pd.Timestamp(origin)
    w = weekly[weekly.index + pd.Timedelta(days=6) < o]
    known_src = w["source"].dropna()
    if not len(known_src):
        return None
    cur = known_src.iloc[-1]
    other = known_src[known_src != cur]
    if mode == "current" and len(other):
        w = w[w.index > other.index[-1]]
    vals = w[column].where(w["source"] == cur) if mode == "current" else w[column].where(w["source"].notna())
    vals = vals.iloc[-max_weeks:]
    if vals.notna().sum() < min_weeks:
        return None
    return vals.to_numpy(dtype=float), w.index[-1]


Predictor = Callable[[list[np.ndarray], int], np.ndarray]  # contexts, steps -> (n, steps) medians


def chronos2_pipeline(model_id: str = "amazon/chronos-2", device: str = "cpu"):
    from chronos import BaseChronosPipeline

    return BaseChronosPipeline.from_pretrained(model_id, device_map=device)


def predictor_from(pipe, point: str = "median") -> Predictor:
    """Median (or mean) forecasts from a loaded Chronos-2 pipeline."""

    def predict(ctx: list[np.ndarray], steps: int) -> np.ndarray:
        q, mean = pipe.predict_quantiles([c.astype(np.float32) for c in ctx], prediction_length=steps,
                                         quantile_levels=[0.5])
        if point == "mean":
            return np.stack([np.asarray(m[0, :], dtype=float) for m in mean])
        return np.stack([np.asarray(x[0, :, 0], dtype=float) for x in q])

    return predict


def chronos2_predictor(model_id: str = "amazon/chronos-2", device: str = "cpu") -> Predictor:
    """Median forecasts from a locally run Chronos-2 (weights from Hugging Face, Apache-2.0)."""
    return predictor_from(chronos2_pipeline(model_id, device))


def weekly_path_forecasts(weekly: pd.DataFrame, origins: list[date], column: str, predictor: Predictor,
                          horizon_days: int = 400, min_weeks: int = 26, max_weeks: int = 520,
                          mode: str = "current") -> dict[date, pd.Series]:
    """Per origin: a daily-indexed Series of the forecast weekly value for each day from the week
    after the last context week to ``origin + horizon_days``."""
    ctx, last, keep = [], [], []
    for o in origins:
        c = contexts(weekly, o, column, min_weeks, max_weeks, mode)
        if c is not None:
            ctx.append(c[0])
            last.append(c[1])
            keep.append(o)
    out: dict[date, pd.Series] = {}
    if not ctx:
        return out
    steps = max(int(np.ceil(((pd.Timestamp(o) + pd.Timedelta(days=horizon_days)) - lw).days / 7)) + 1
                for o, lw in zip(keep, last))
    preds = predictor(ctx, steps)
    for o, lw, p in zip(keep, last, preds):
        weeks = lw + pd.to_timedelta(7 * np.arange(1, steps + 1), unit="D")
        days = pd.date_range(weeks[0], weeks[-1] + pd.Timedelta(days=6))
        out[o] = pd.Series(np.repeat(p, 7), index=days)
    return out


def track_b_rows(milk_base: pd.DataFrame, herd: pd.DataFrame, ypc_paths: dict, litre_paths: dict) -> pd.DataFrame:
    """Rows of ``chronos2_ypc_x_engine`` (engine mean milking cows of the period x forecast litres
    per cow per day, summed over the period's days) and ``chronos2_milk`` (forecast herd litres
    per day summed), for the base model's weekly and monthly periods."""
    m = _keyed(milk_base)
    m = m[m["grain"].isin(["weekly", "monthly"])].drop_duplicates(KEYS)
    h = _keyed(herd[(herd["series"] == "milking") & (herd["model"] == "herd_engine")]).drop_duplicates(KEYS)
    cows = h.set_index(KEYS)["forecast"]
    rows = []
    for r in m.itertuples(index=False):
        days = pd.date_range(pd.Timestamp(r.period_start), pd.Timestamp(r.period_end) - pd.Timedelta(days=1))
        base = dict(origin=r.origin, grain=r.grain, horizon=int(r.horizon), period_start=r.period_start,
                    period_end=r.period_end, series="herd_milk", actual=r.actual)
        if "band" in m.columns:
            base["band"] = r.band
        yp = ypc_paths.get(r.origin)
        k = (r.grain, int(r.horizon), r.origin, r.period_start)
        if yp is not None and k in cows.index and days.isin(yp.index).all():
            rows.append(dict(base, model="chronos2_ypc_x_engine",
                             forecast=float(cows.loc[k] * yp.loc[days].sum())))
        lp = litre_paths.get(r.origin)
        if lp is not None and days.isin(lp.index).all():
            rows.append(dict(base, model="chronos2_milk", forecast=float(lp.loc[days].sum())))
    out = pd.DataFrame(rows)
    if len(out):
        out["error"] = out["forecast"] - out["actual"]
    return out


@dataclass
class TrackBResult:
    rows: pd.DataFrame
    hits: pd.DataFrame
    hits_y: pd.DataFrame
    checks: pd.DataFrame
    keep: bool
    coverage: pd.DataFrame


def run_track_b(milk_errors: pd.DataFrame, herd_errors: pd.DataFrame, daily: pd.DataFrame,
                predictor: Predictor, base_model: str = "milk_baseline_adaptive") -> TrackBResult:
    base = _keyed(milk_errors[milk_errors["model"] == base_model])
    if "series" in base:
        base = base[base["series"] == "herd_milk"]
    base = base[(base["origin"] >= DEV_START) & (base["origin"] < DEV_END)]
    wk = weekly_series(daily[pd.to_datetime(daily["date"]) < pd.Timestamp(DEV_END)])
    origins = sorted(set(base.loc[base["grain"].isin(["weekly", "monthly"]), "origin"]))
    ypc = weekly_path_forecasts(wk, origins, "ypc", predictor)
    lit = weekly_path_forecasts(wk, origins, "litres", predictor)
    rows = track_b_rows(base, herd_errors, ypc, lit)
    trusted = base[base["band"].isin(VERIFIED_BANDS)] if "band" in base else base
    cov = []
    for mname in ("chronos2_ypc_x_engine", "chronos2_milk"):
        r = rows[rows["model"] == mname] if len(rows) else rows
        for (g, h), b in trusted[trusted["grain"].isin(["weekly", "monthly"])].groupby(["grain", "horizon"]):
            have = set(zip(r["origin"], r["period_start"])) if len(r) else set()
            n_have = sum((o, s) in have for o, s in zip(b["origin"], b["period_start"]))
            cov.append(dict(model=mname, grain=g, horizon=int(h), trusted_base=len(b), issued=n_have))
    frames = {base_model: trusted}
    for mname in ("chronos2_ypc_x_engine", "chronos2_milk"):
        if len(rows) and (rows["model"] == mname).any():
            frames[mname] = rows[rows["model"] == mname]
    hits, hits_y = pd.DataFrame(), pd.DataFrame()
    checks, keep = pd.DataFrame(), False
    if "chronos2_ypc_x_engine" in frames:
        pair = {base_model: trusted, "chronos2_ypc_x_engine": frames["chronos2_ypc_x_engine"]}
        hits, hits_y = matched_hits(pair), matched_hits(pair, by_year=True)
        if "chronos2_milk" in frames:
            pm = {base_model: trusted, "chronos2_milk": frames["chronos2_milk"]}
            hits = pd.concat([hits, matched_hits(pm).query("model == 'chronos2_milk'")], ignore_index=True)
            hits_y = pd.concat([hits_y, matched_hits(pm, by_year=True).query("model == 'chronos2_milk'")],
                               ignore_index=True)
        checks, keep = track_b_rule(hits, hits_y, base_model, "chronos2_ypc_x_engine")
    return TrackBResult(rows=rows, hits=hits, hits_y=hits_y, checks=checks, keep=keep,
                        coverage=pd.DataFrame(cov))
