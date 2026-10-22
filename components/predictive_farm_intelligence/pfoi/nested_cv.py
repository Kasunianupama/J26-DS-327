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


def _miss10(rows: pd.DataFrame) -> float:
    """Share of forecasts more than 10 % from the record (1 - hit rate within +-10 %)."""
    r = rows[rows["actual"] > 0]
    if not len(r):
        return np.nan
    return float(((r["forecast"] - r["actual"]).abs() / r["actual"] > 0.10 + 1e-9).mean())


METRICS = {"wape": _wape, "miss10": _miss10}


def nested_select(candidates: dict[str, pd.DataFrame], objectives: list[tuple[str, str, int]],
                  fold_years=FOLD_YEARS, min_inner: int = MIN_INNER_PERIODS,
                  metric: str = "wape", fallback: str | None = None) -> NestedResult:
    """``candidates``: name -> error rows of that candidate (one model per frame).

    Inner score at fold Y = mean ``metric`` (WAPE, or ``miss10`` = share outside +-10 %) over
    the objectives that have at least ``min_inner`` common periods ending on or before 1 Jan Y.
    Ties go to the first candidate in order. A fold with no inner score uses ``fallback``
    (if given) instead of being skipped.
    """
    score = METRICS[metric]
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
                scores[c].append(score(p))
        means = {c: (float(np.mean(v)) if v else np.nan) for c, v in scores.items()}
        valid = {c: m for c, m in means.items() if not np.isnan(m)}
        choice = min(valid, key=lambda c: (valid[c], list(cands).index(c))) if valid else fallback
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


DEVELOPMENT_YEARS = tuple(range(2017, 2024))


def choose_trend_by_year(errors: pd.DataFrame, base_model: str, cfg, grid, years=DEVELOPMENT_YEARS,
                         metric: str = "miss10", min_inner: int = MIN_INNER_PERIODS,
                         breaks: list | None = None):
    """Damped-trend settings of the adaptive correction chosen year by year (pfoi-1.2.1-dev).

    Candidates: the plain level ("off", today's ``<base>_adaptive``) and one corrected series
    per ``TrendConfig`` in ``grid``. For forecast year Y the candidate with the fewest misses
    beyond +-10 % on periods that had ended by 1 Jan Y (all horizons of the series, equal
    weight) is used for the origins of Y; ties and years with no earlier periods use "off".
    Returns (off rows, chosen rows as ``<base>_adaptive_trend`` with column ``trend_setting``,
    fold table).
    """
    from .adaptive import adaptive_corrected

    off = adaptive_corrected(errors, base_model, f"{base_model}_adaptive", cfg, breaks=breaks)
    cands = {"off": off}
    for t in grid:
        if not t.off:
            cands[t.label()] = adaptive_corrected(errors, base_model, cfg=cfg, breaks=breaks, trend=t)
    objectives = sorted({(s, g, int(h)) for s, g, h in off[["series", "grain", "horizon"]].itertuples(index=False)})
    res = nested_select(cands, objectives, fold_years=years, min_inner=min_inner,
                        metric=metric, fallback="off")
    chosen = res.selected_rows
    if len(chosen):
        chosen = (chosen.drop(columns="fold_year").rename(columns={"candidate": "trend_setting"})
                  .assign(model=f"{base_model}_adaptive_trend"))
    return off, chosen, res.folds
