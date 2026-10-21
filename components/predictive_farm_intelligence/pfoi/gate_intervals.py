"""pfoi-1.2.1-dev: 1.2.0-dev forecasts with a gate confidence flag and gate-conditional intervals.

The stability gate (G1, ``gate.py``) recognises unstable regimes (within-cell AUC 0.776) but no
specialist beat 1.2.0-dev (G2). So 1.2.1-dev keeps every 1.2.0-dev point forecast unchanged and uses
the gate only to say how sure each forecast is:

* **Confidence flag:** ``low`` when the G1 logistic gate's probability of a miss beyond +-10 % is
  above 0.5, else ``normal``. The probability comes from the forward-chained gate (fitted on labels
  that ended before 1 January of the forecast year). Rows without their own gate probability (no
  trusted milk label, herd series) use the mean of the gate probabilities of the same origin and grain.
* **Gate-conditional (Mondrian) intervals:** the 80 % / 90 % range of a forecast comes from the same
  series' own past log errors (actual / forecast) at that grain and horizon, finished by the forecast
  date, **taken only from past forecasts with the same confidence flag** (at least ``MIN_CAL``; else
  all past forecasts of that cell). A finite-sample conformal level ``min(1, L (n + 1) / n)`` is used.
  ``pooled`` intervals (same rule, ignoring the flag) are computed on the same rows as the reference.

Calibration uses only forecasts whose gate probability exists (from 2019) and whose period ended by
the forecast date, so intervals are evaluated from 2020. Milk is evaluated on trusted periods; herd
stocks (milking cows, total herd) get the same flag and method and are reported, not ruled on.

Keep rule (fixed 2026-10-22, before any real-data run; milk, trusted, forecast years 2020-2023, all
horizons together, 90 % range):

1. low-confidence forecasts: the gate-conditional coverage is closer to 0.90 than the pooled coverage,
   and at least 0.80;
2. normal forecasts: gate-conditional coverage at least 0.85, and mean relative width at most 10 %
   above the pooled width;
3. all forecasts: gate-conditional coverage between 0.85 and 0.95.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

KEYS = ["grain", "horizon", "origin", "period_start"]
LEVELS = (0.8, 0.9)
MIN_CAL = 19
FLAG_THRESHOLD = 0.5
EVAL_FROM_YEAR = 2020
VERSION = "pfoi-1.2.1-dev"
RULE_LEVEL = 0.9
RULE_LOW_MIN = 0.80
RULE_NORMAL_MIN = 0.85
RULE_MAX_WIDER = 0.10
RULE_ALL = (0.85, 0.95)


def _norm(rows: pd.DataFrame) -> pd.DataFrame:
    r = rows.copy()
    for c in ("origin", "period_start", "period_end"):
        if c in r:
            r[c] = pd.to_datetime(r[c]).dt.date
    r["horizon"] = r["horizon"].astype(int)
    return r


def attach_gate(rows: pd.DataFrame, probs: pd.DataFrame, col: str = "p_logistic",
                threshold: float = FLAG_THRESHOLD) -> pd.DataFrame:
    """Add ``p_gate`` (own key, else mean of the same origin and grain) and ``confidence``."""
    r, p = _norm(rows), _norm(probs)
    own = p.drop_duplicates(KEYS).set_index(KEYS)[col]
    by_origin = p.groupby(["grain", "origin"])[col].mean()
    key = pd.MultiIndex.from_frame(r[KEYS])
    pg = own.reindex(key).to_numpy(dtype=float)
    fb = by_origin.reindex(pd.MultiIndex.from_frame(r[["grain", "origin"]])).to_numpy(dtype=float)
    r["p_gate"] = np.where(np.isfinite(pg), pg, fb)
    r["confidence"] = np.where(~np.isfinite(r["p_gate"]), None,
                               np.where(r["p_gate"] > threshold, "low", "normal"))
    return r


def _quantiles(err: np.ndarray, level: float) -> tuple[float, float]:
    n = len(err)
    lv = min(1.0, level * (n + 1) / n)
    return float(np.quantile(err, (1 - lv) / 2)), float(np.quantile(err, (1 + lv) / 2))


def mondrian_intervals(rows: pd.DataFrame, levels=LEVELS, min_cal: int = MIN_CAL) -> pd.DataFrame:
    """Per row: ``lo_*``/``hi_*`` (gate-conditional) and ``plo_*``/``phi_*`` (pooled) for each
    level, from past rows of the same series x grain x horizon whose period ended by the origin."""
    out = rows.copy()
    for L in levels:
        for c in (f"lo_{L:g}", f"hi_{L:g}", f"plo_{L:g}", f"phi_{L:g}"):
            out[c] = np.nan
    out["n_cal_flag"] = 0
    for _, g in out.groupby(["series", "grain", "horizon"]):
        ok = (g["forecast"] > 0) & (g["actual"] > 0) & g["confidence"].notna()
        ends = pd.to_datetime(g["period_end"]).to_numpy()
        origins = pd.to_datetime(g["origin"]).to_numpy()
        err = np.log(g["actual"].where(ok) / g["forecast"].where(ok)).to_numpy(dtype=float)
        flag = g["confidence"].to_numpy()
        f = g["forecast"].to_numpy(dtype=float)
        for i, ix in enumerate(g.index):
            if not isinstance(flag[i], str):
                continue
            past = (ends <= origins[i]) & np.isfinite(err)
            same = past & (flag == flag[i])
            out.at[ix, "n_cal_flag"] = int(same.sum())
            if past.sum() < min_cal:
                continue
            for L in levels:
                pl, ph = _quantiles(err[past], L)
                use = same if same.sum() >= min_cal else past
                ql, qh = _quantiles(err[use], L)
                out.at[ix, f"lo_{L:g}"], out.at[ix, f"hi_{L:g}"] = f[i] * np.exp(ql), f[i] * np.exp(qh)
                out.at[ix, f"plo_{L:g}"], out.at[ix, f"phi_{L:g}"] = f[i] * np.exp(pl), f[i] * np.exp(ph)
    return out


def interval_scores(rows: pd.DataFrame, levels=LEVELS, from_year: int = EVAL_FROM_YEAR,
                    by=("series", "confidence")) -> pd.DataFrame:
    """Coverage and mean relative width (upper - lower) / forecast of both methods."""
    r = rows[(pd.to_datetime(rows["origin"]).dt.year >= from_year) & rows[f"lo_{levels[-1]:g}"].notna()]
    out = []
    groups = [((), r)] + list(r.groupby(list(by))) if by else [((), r)]
    for key, g in groups:
        key = key if isinstance(key, tuple) else (key,)
        row = dict(zip(by, key)) if key else {k: "all" for k in by}
        row["n"] = len(g)
        for L in levels:
            for m, (lo, hi) in (("gate", (f"lo_{L:g}", f"hi_{L:g}")), ("pooled", (f"plo_{L:g}", f"phi_{L:g}"))):
                inside = (g["actual"] >= g[lo]) & (g["actual"] <= g[hi])
                row[f"cov{int(L * 100)}_{m}"] = float(inside.mean()) if len(g) else np.nan
                row[f"width{int(L * 100)}_{m}"] = float(((g[hi] - g[lo]) / g["forecast"]).mean()) if len(g) else np.nan
        out.append(row)
    return pd.DataFrame(out)


def interval_rule(milk_scores: pd.DataFrame):
    """Pre-registered 1.2.1-dev rule on milk scores by confidence (``interval_scores`` with
    by=("confidence",)). Returns (checks, keep)."""
    s = milk_scores.set_index("confidence")
    c, w = f"cov{int(RULE_LEVEL * 100)}", f"width{int(RULE_LEVEL * 100)}"
    rows = []
    if "low" in s.index:
        g, p = s.loc["low", f"{c}_gate"], s.loc["low", f"{c}_pooled"]
        rows.append(dict(check="low: coverage closer to 0.90 than pooled", value=float(abs(p - 0.9) - abs(g - 0.9)),
                         passed=bool(abs(g - 0.9) < abs(p - 0.9))))
        rows.append(dict(check=f"low: coverage >= {RULE_LOW_MIN}", value=float(g), passed=bool(g >= RULE_LOW_MIN)))
    else:
        rows.append(dict(check="low-confidence forecasts exist", value=0.0, passed=False))
    if "normal" in s.index:
        g = s.loc["normal", f"{c}_gate"]
        wider = s.loc["normal", f"{w}_gate"] / s.loc["normal", f"{w}_pooled"] - 1
        rows.append(dict(check=f"normal: coverage >= {RULE_NORMAL_MIN}", value=float(g), passed=bool(g >= RULE_NORMAL_MIN)))
        rows.append(dict(check=f"normal: width at most {RULE_MAX_WIDER:.0%} above pooled", value=float(wider),
                         passed=bool(wider <= RULE_MAX_WIDER + 1e-12)))
    a = s.loc["all", f"{c}_gate"] if "all" in s.index else np.nan
    rows.append(dict(check=f"all: coverage in {RULE_ALL}", value=float(a),
                     passed=bool(np.isfinite(a) and RULE_ALL[0] <= a <= RULE_ALL[1])))
    checks = pd.DataFrame(rows)
    return checks, bool(checks["passed"].all())


def build_121(milk: pd.DataFrame, probs: pd.DataFrame, herd: pd.DataFrame | None = None) -> pd.DataFrame:
    """1.2.1-dev rows: the 1.2.0-dev forecasts (unchanged) with confidence, p_gate and both
    interval sets; herd stocks included when given. ``model_version`` = pfoi-1.2.1-dev."""
    parts = [milk.assign(series="herd_milk") if "series" not in milk else milk]
    if herd is not None and len(herd):
        parts.append(herd)
    rows = attach_gate(pd.concat(parts, ignore_index=True), probs)
    out = mondrian_intervals(rows)
    out["model_version"] = VERSION
    return out
