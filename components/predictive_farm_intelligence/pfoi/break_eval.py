"""Evaluate the break reset (PP1 improvement 1a) on saved backtest errors.

Recomputes the correction layer's models with and without the reset on the same error
files, so no backtest is re-run: herd ``herd_engine_corrected`` (2-year mean past error)
and milk ``milk_baseline_adaptive`` (adaptive level, pfoi-1.1.0 settings). Accuracy is
reported over all forecast dates and over the dates 0-5 whole months after the latest break
detected at the forecast date.

Keep rule (fixed before evaluation, docs/pp1_plan.md): keep the reset if accuracy after
breaks improves for herd milk (weekly 4 weeks, monthly 3 months) and milking cows (monthly
3 and 6 months) and accuracy over all dates drops by at most 1 point for every key row.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .adaptive import adaptive_corrected
from .breaks import latest_break
from .error_tools import bias_corrected

KEY_ROWS = (("herd_milk", "weekly", 4), ("herd_milk", "monthly", 3), ("milking", "monthly", 3),
            ("milking", "monthly", 6), ("n_herd", "monthly", 6), ("n_herd", "monthly", 12),
            ("calvings", "monthly", 3))
HERD_BASE, MILK_BASE = "herd_engine", "milk_baseline"


def with_reset(herd: pd.DataFrame | None, milk: pd.DataFrame | None, breaks: list[date],
               adaptive_cfg) -> pd.DataFrame:
    """Rows of the corrected models without (``*_corrected`` / ``*_adaptive``) and with the
    reset (``..._br``), for every forecast in the given error tables."""
    parts = []
    if herd is not None and len(herd):
        parts += [bias_corrected(herd, HERD_BASE),
                  bias_corrected(herd, HERD_BASE, new_model=f"{HERD_BASE}_corrected_br", breaks=breaks)]
    if milk is not None and len(milk):
        parts += [adaptive_corrected(milk, MILK_BASE, cfg=adaptive_cfg),
                  adaptive_corrected(milk, MILK_BASE, new_model=f"{MILK_BASE}_adaptive_br",
                                     cfg=adaptive_cfg, breaks=breaks)]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def after_break(origins: pd.Series, breaks: list[date], months: int = 6) -> np.ndarray:
    """True where the forecast date is 0-``months - 1`` whole months after a known break."""
    out = []
    for o in pd.to_datetime(origins):
        b = latest_break(o.date(), breaks)
        if b is None:
            out.append(False)
            continue
        bd = pd.Timestamp(b)
        m = (o.year - bd.year) * 12 + o.month - bd.month - (o.day < bd.day)
        out.append(0 <= m < months)
    return np.array(out, dtype=bool)


def compare(rows: pd.DataFrame, breaks: list[date], score_from: date | None = None) -> pd.DataFrame:
    """Accuracy (1 - WAPE) of each model with and without the reset, all dates and after breaks."""
    r = rows.copy()
    if score_from is not None:
        r = r[pd.to_datetime(r["origin"]).dt.date >= score_from]
    r["after"] = after_break(r["origin"], breaks)
    r["abs"] = (r["forecast"] - r["actual"]).abs()
    acc = lambda d: 1 - d["abs"].sum() / d["actual"].sum() if len(d) and d["actual"].sum() else np.nan  # noqa: E731
    out = []
    for series, grain, h in KEY_ROWS:
        sub = r[(r["series"] == series) & (r["grain"] == grain) & (r["horizon"] == h)]
        for model, g in sub.groupby("model"):
            out.append(dict(series=series, grain=grain, horizon=h, model=model, n=len(g),
                            accuracy=acc(g), n_after=int(g["after"].sum()), after_break=acc(g[g["after"]])))
    return pd.DataFrame(out)


def verdict(table: pd.DataFrame) -> tuple[bool, list[str]]:
    """Apply the keep rule; returns (keep, reasons)."""
    reasons = []
    ok = True
    for series, grain, h in KEY_ROWS:
        sub = table[(table["series"] == series) & (table["grain"] == grain) & (table["horizon"] == h)]
        base = sub[~sub["model"].str.endswith("_br")]
        new = sub[sub["model"].str.endswith("_br")]
        if not len(base) or not len(new):
            ok = False
            reasons.append(f"{series} {grain} h{h}: missing comparison (decision incomplete)")
            continue
        if len(base) != 1 or len(new) != 1:
            ok = False
            reasons.append(f"{series} {grain} h{h}: duplicate comparison (decision incomplete)")
            continue
        b, n = base.iloc[0], new.iloc[0]
        values = [b[k] for k in ("n", "n_after", "accuracy", "after_break")]
        values += [n[k] for k in ("n", "n_after", "accuracy", "after_break")]
        if (not np.isfinite(values).all() or b["n"] <= 0 or b["n_after"] <= 0
                or b["n"] != n["n"] or b["n_after"] != n["n_after"]):
            ok = False
            reasons.append(f"{series} {grain} h{h}: invalid or unmatched samples (decision incomplete)")
            continue
        if n["accuracy"] < b["accuracy"] - 0.01:
            ok = False
            reasons.append(f"{series} {grain} h{h}: all-dates accuracy {b['accuracy']:.3f} -> {n['accuracy']:.3f}")
        must_improve = (series, grain, h) in (("herd_milk", "weekly", 4), ("herd_milk", "monthly", 3),
                                             ("milking", "monthly", 3), ("milking", "monthly", 6))
        if must_improve and not (n["after_break"] > b["after_break"]):
            ok = False
            reasons.append(f"{series} {grain} h{h}: after-break accuracy {b['after_break']:.3f} -> "
                           f"{n['after_break']:.3f} (must improve)")
    return ok, reasons
