"""Nested, purged rolling validation of model choices (leakage audit L9).

pfoi-1.0.0 picked its options (window, curve, k) on the development block and was then
scored on the same block, which flatters the result. Here every choice is made
year by year: for validation year Y the candidates are compared only on forecasts whose
target period had **ended before 1 January of Y** (purge), the best one is selected, and
only that one is scored on the origins of year Y. The nested score is what a forecaster
choosing as they went would have achieved; the gap to the best candidate in hindsight is
the optimism of picking on the same data.

Works on backtest error tables only (one per candidate, as written by the backtests), so
it needs no data access and is tested on synthetic tables.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from .scorecard import TARGETS

FOLD_YEARS = (2019, 2020, 2021, 2022, 2023)
MIN_INNER_PERIODS = 12
KEYS = ["origin", "period_start"]


def default_objectives(series: tuple[str, ...]) -> list[tuple[str, str, int]]:
    """(series, grain, horizon) of every agreed accuracy target for these series."""
    return [(s, g, h) for (s, g), by_h in TARGETS.items() if s in series for h in by_h]


@dataclass
class NestedResult:
    folds: pd.DataFrame      # fold_year, candidate, inner_score, n_objectives, selected
    summary: pd.DataFrame    # per objective: nested and per-candidate accuracy, optimism
    selected_rows: pd.DataFrame  # outer-fold forecasts of the selected candidates


def _prep(frame: pd.DataFrame) -> pd.DataFrame:
    f = frame.copy()
    for col in ("origin", "period_start", "period_end"):
        f[col] = pd.to_datetime(f[col]).dt.date
    f["horizon"] = f["horizon"].astype(int)
    return f


def _objective_rows(cands: dict[str, pd.DataFrame], obj: tuple[str, str, int]) -> dict[str, pd.DataFrame]:
    """Rows of one objective, restricted to periods every candidate forecast."""
    s, g, h = obj
    parts = {c: f[(f["series"] == s) & (f["grain"] == g) & (f["horizon"] == h)] for c, f in cands.items()}
    common = None
    for p in parts.values():
        k = set(map(tuple, p[KEYS].to_numpy()))
        common = k if common is None else common & k
    if not common:
        return {c: p.iloc[0:0] for c, p in parts.items()}
    return {c: p[[tuple(x) in common for x in p[KEYS].to_numpy()]] for c, p in parts.items()}


def _wape(rows: pd.DataFrame) -> float:
    tot = rows["actual"].sum()
    return float((rows["forecast"] - rows["actual"]).abs().sum() / tot) if tot > 0 else np.nan


def nested_select(candidates: dict[str, pd.DataFrame], objectives: list[tuple[str, str, int]],
                  fold_years=FOLD_YEARS, min_inner: int = MIN_INNER_PERIODS) -> NestedResult:
    """``candidates``: name -> error rows of that candidate (one model per frame).

    Inner score at fold Y = mean WAPE over the objectives that have at least ``min_inner``
    common periods ending on or before 1 Jan Y. Ties go to the first candidate in order.
    """
    cands = {c: _prep(f) for c, f in candidates.items()}
    per_obj = {obj: _objective_rows(cands, obj) for obj in objectives}
    fold_rows, picked = [], []
    for year in fold_years:
        start, end = date(year, 1, 1), date(year + 1, 1, 1)
        scores = {c: [] for c in cands}
        for obj, parts in per_obj.items():
            inner = {c: p[p["period_end"] <= start] for c, p in parts.items()}
            if min(len(p) for p in inner.values()) < min_inner:
                continue
            for c, p in inner.items():
                scores[c].append(_wape(p))
        means = {c: (float(np.mean(v)) if v else np.nan) for c, v in scores.items()}
        valid = {c: m for c, m in means.items() if not np.isnan(m)}
        choice = min(valid, key=lambda c: (valid[c], list(cands).index(c))) if valid else None
        for c in cands:
            fold_rows.append(dict(fold_year=year, candidate=c, inner_score=means[c],
                                  n_objectives=len(scores[c]), selected=(c == choice)))
        if choice is None:
            continue
        for obj, parts in per_obj.items():
            p = parts[choice]
            o = p[(p["origin"] >= start) & (p["origin"] < end)]
            if len(o):
                picked.append(o.assign(fold_year=year, candidate=choice))
    folds = pd.DataFrame(fold_rows)
    sel = pd.concat(picked, ignore_index=True) if picked else pd.DataFrame()
    return NestedResult(folds=folds, summary=_summary(per_obj, sel, fold_years), selected_rows=sel)


def _summary(per_obj, sel: pd.DataFrame, fold_years) -> pd.DataFrame:
    rows = []
    lo, hi = date(min(fold_years), 1, 1), date(max(fold_years) + 1, 1, 1)
    for (s, g, h), parts in per_obj.items():
        row = dict(series=s, grain=g, horizon=h)
        for c, p in parts.items():
            o = p[(p["origin"] >= lo) & (p["origin"] < hi)]
            row[f"acc_{c}"] = 1 - _wape(o) if len(o) else np.nan
        mine = sel[(sel["series"] == s) & (sel["grain"] == g) & (sel["horizon"] == h)] if len(sel) else sel
        row["n"] = len(mine)
        row["acc_nested"] = 1 - _wape(mine) if len(mine) else np.nan
        fixed = [v for k, v in row.items() if k.startswith("acc_") and k != "acc_nested" and not np.isnan(v)]
        row["acc_best_in_hindsight"] = max(fixed) if fixed else np.nan
        row["optimism"] = row["acc_best_in_hindsight"] - row["acc_nested"]
        rows.append(row)
    return pd.DataFrame(rows)
