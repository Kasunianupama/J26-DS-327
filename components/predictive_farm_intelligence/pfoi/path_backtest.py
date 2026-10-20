"""Backtest of the pfoi-1.1.1 daily path: days and weeks up to 12 months ahead.

pfoi-1.1.1 publishes every day and every week of the next 12 months, reconciled top-down to
the pfoi-1.1.0 corrected months (``outlook.reconcile``). The weekly-origin backtests score
only days 1/7/14 and weeks 1/4/8/13 of a per-grain forecast, so they cannot say how good
the published days and weeks are. Here the published forecast itself is replayed at each
monthly forecast date (the only kind of origin it is issued at):

1. the frozen 1.1.0 engine and milk model run with facts before the origin only;
2. the correction layer is built from backtest errors whose period ended by the origin;
3. the days are reconciled, and days and weeks are scored at ``PATH_HORIZONS`` against the
   recorded herd panel and herd milk (a milk period counts only when every day in it is
   scoreable and from one source; nothing is imputed).

Rows are written for the reconciled forecast (``pfoi_reconciled``) and the structural one
(``pfoi_structural``), with 5 %/95 % intervals and coverage from each model's own past
errors (``error_tools.add_intervals``). Series use the page names (milk_litres, milking,
total_herd, ...). Outputs are herd-level aggregates only.
"""
from __future__ import annotations

from datetime import date
from typing import Callable

import numpy as np
import pandas as pd

from .backtest_herd import TEST_START, check_block
from .backtest_milk import _target_frame, period_actual
from .data import DATA_START, SnapshotSource, prefetch_snapshots
from .error_tools import add_intervals
from .milk_baseline import MilkHistory
from .outlook import RECONCILED_MODEL, build_output_layer, path_end, run_model
from .page_run import SERIES
from .periods import period_bounds

STRUCTURAL_MODEL = "pfoi_structural"
PATH_HORIZONS = {"daily": (1, 7, 14, 30, 61, 91, 182, 273, 365),
                 "weekly": (1, 4, 8, 13, 26, 39, 51)}
HERD_PAGE_SERIES = tuple(s for s in SERIES if s != "milk_litres")


def _value(frame: pd.DataFrame, cols, stock: bool) -> float:
    v = frame[list(cols)].sum(axis=1)
    return float(v.mean() if stock else v.sum())


def score_path_origin(source, origin: date, errors: pd.DataFrame | None, cfg, mcfg, adaptive_cfg,
                      herd_series, hist: MilkHistory, t: pd.DataFrame, panel: pd.DataFrame,
                      score_until: date, cache: dict | None = None) -> list[dict]:
    """Error rows of one monthly forecast date (reconciled and structural)."""
    run = run_model(source, origin, cfg, mcfg, hist=hist, cache=cache)
    run.layer = build_output_layer(errors, origin, adaptive_cfg, herd_series)
    run.reconciled = True
    models = {RECONCILED_MODEL: run.path(), STRUCTURAL_MODEL: run.daily}
    mdates = {m: pd.to_datetime(d["date"]).dt.date for m, d in models.items()}
    pdates = pd.to_datetime(panel["date"]).dt.date
    end = path_end(origin)
    rows = []
    for grain, horizons in PATH_HORIZONS.items():
        for h in horizons:
            s, e = period_bounds(run.starts[grain], grain, h)
            if e > end or e > score_until:
                continue
            actual = {}
            milk = period_actual(t, s, e)
            if milk is not None:
                actual["milk_litres"] = (milk[0], milk[1])
            act_part = panel.loc[(pdates >= s) & (pdates < e)]
            if len(act_part) == (e - s).days:
                for sid in HERD_PAGE_SERIES:
                    cols, stock, _ = SERIES[sid]
                    if all(c in act_part.columns for c in cols):
                        actual[sid] = (_value(act_part, cols, stock), None)
            for model, daily in models.items():
                part = daily.loc[(mdates[model] >= s) & (mdates[model] < e)]
                if len(part) != (e - s).days:
                    continue
                for sid, (a, src) in actual.items():
                    cols, stock, _ = SERIES[sid]
                    rows.append(dict(origin=origin, grain=grain, horizon=h, period_start=s, period_end=e,
                                     series=sid, model=model, forecast=_value(part, cols, stock),
                                     actual=a, source=src, flags=run.flag))
    return rows


def run_path_backtest(source, origins: list[date], errors: pd.DataFrame | None, cfg, mcfg,
                      adaptive_cfg, herd_series, score_until: date = TEST_START,
                      block: str = "development", prior: pd.DataFrame | None = None,
                      progress: Callable[[int, int, date], None] | None = None) -> pd.DataFrame:
    """Path errors at monthly ``origins``. ``errors``: the backtest errors the correction
    layer learns from (only those ended by each origin are used). ``prior``: earlier path
    errors (development) that a later block's intervals may learn from."""
    if any(o.day != 1 for o in origins):
        raise ValueError("path backtest origins are the first day of a month")
    check_block(origins, score_until, block)
    hist = MilkHistory(cowdays=source.milking_cowdays(DATA_START, score_until),
                       target=source.target_daily(DATA_START, score_until))
    t = _target_frame(hist.target)
    panel = source.panel_daily(DATA_START, score_until)
    snap = SnapshotSource(source, prefetch_snapshots(source, origins, cfg))
    cache: dict = {}
    rows = []
    for i, origin in enumerate(origins):
        if progress:
            progress(i, len(origins), origin)
        try:
            rows += score_path_origin(snap, origin, errors, cfg, mcfg, adaptive_cfg, herd_series,
                                      hist, t, panel, score_until, cache)
        except ValueError:  # e.g. no clean milk months to anchor k: no forecast issued
            continue
    out = pd.DataFrame(rows)
    if not len(out):
        return out
    out["error"] = out["forecast"] - out["actual"]
    if prior is not None and len(prior):
        p = prior[[c for c in out.columns if c in prior.columns]].copy()
        for col in ("origin", "period_start", "period_end"):
            p[col] = pd.to_datetime(p[col]).dt.date
        work = pd.concat([p.assign(_prior=True), out.assign(_prior=False)], ignore_index=True)
    else:
        work = out.assign(_prior=False)
    work = add_intervals(work)
    return work[~work["_prior"].astype(bool)].drop(columns="_prior").reset_index(drop=True)


def summarise_path(errors: pd.DataFrame) -> pd.DataFrame:
    """n, MAE, relative MAE, bias and 90 % coverage by grain x horizon x series x model."""
    if not len(errors):
        return pd.DataFrame()
    e = errors.assign(abs_err=errors["error"].abs(),
                      rel=(errors["error"].abs() / errors["actual"]).where(errors["actual"] > 0))
    g = e.groupby(["grain", "horizon", "series", "model"])
    out = pd.DataFrame({"n": g.size(), "mae": g["abs_err"].mean(), "mape_pct": 100 * g["rel"].mean(),
                        "bias": g["error"].mean()})
    if "covered" in e:
        out["coverage_pct"] = 100 * g["covered"].mean()
    return out.reset_index().replace({np.inf: np.nan})
