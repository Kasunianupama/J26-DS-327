"""Rolling-origin backtest of herd milk (development block, H1).

At each origin: herd engine (Step 3) + lactation curve + calibration k give the milk
baseline; benchmarks (persistence, seasonal naive, ETS, SARIMA) see the same history.
Monthly origins score months 1/3/6/12; weekly origins (Mondays) score weeks 1/4/8/13
and days 1/7/14. A period is scored only if every day in it is scoreable and from one
source; nothing is imputed. Targets on or after 2024-01-01 are never scored here.

Also added: a bias-corrected baseline (own past errors) and, for every model, empirical
5%/95% intervals from that model's own past relative errors (coverage from 2018).
Outputs are herd-level aggregates only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable

import numpy as np
import pandas as pd

from . import MODEL_VERSION
from .backtest_herd import TEST_START, check_block, development_origins
from .benchmarks import ets_forecast, persistence_value, sarima_forecast
from .config import EngineConfig
from .data import DATA_START, SnapshotSource, add_months, load_origin_inputs, prefetch_snapshots
from .error_tools import add_intervals, bias_corrected
from .herd_engine import project
from .parallel import map_origins
from .milk_baseline import MilkConfig, MilkHistory, anchor_k, prepare_milk
from .periods import HORIZONS, horizon_days, period_bounds
from .rates import estimate_rates

BASELINE = "milk_baseline"
CORRECTED = "milk_baseline_corrected"
SERIES = "herd_milk"
GRAINS_BY_ORIGIN = {"monthly": ("monthly",), "weekly": ("weekly", "daily")}


@dataclass
class MilkBacktestResult:
    errors: pd.DataFrame
    notes: pd.DataFrame


def _target_frame(target: pd.DataFrame) -> pd.DataFrame:
    t = target.copy()
    t["date"] = pd.to_datetime(t["date"]).dt.date
    t["ok"] = t["is_scoreable"].fillna(False).astype(bool) & t["target_litres"].notna()
    return t.set_index("date").sort_index()


def period_actual(t: pd.DataFrame, start: date, end: date) -> tuple[float, str] | None:
    """Total litres if every day in [start, end) is scoreable and from one source."""
    part = t.loc[(t.index >= start) & (t.index < end)]
    if len(part) != (end - start).days or not part["ok"].all() or part["target_source"].nunique() != 1:
        return None
    return float(part["target_litres"].sum()), str(part["target_source"].iloc[0])


def benchmark_series(t: pd.DataFrame, origin: date, grain: str) -> pd.Series:
    """Regular series of mean litres/day per period, complete periods before the origin."""
    past = t.loc[t.index < origin]
    ok = past["target_litres"].where(past["ok"])
    if grain == "monthly":
        key = [d.replace(day=1) for d in past.index]
        min_ok = 0.8
        idx = []
        d = DATA_START
        while d < origin.replace(day=1):
            idx.append(d)
            d = add_months(d, 1)
    elif grain == "weekly":
        key = [d - timedelta(days=d.weekday()) for d in past.index]
        min_ok = 5 / 7
        first = DATA_START - timedelta(days=DATA_START.weekday())
        idx = [first + timedelta(days=7 * i) for i in range((origin - first).days // 7)]
    else:
        return ok.iloc[-400:]
    g = pd.DataFrame({"k": key, "v": ok.to_numpy(), "ok": past["ok"].to_numpy()}).groupby("k")
    mean = g["v"].mean()
    share = g["ok"].mean()
    return mean.where(share >= min_ok).reindex(idx)


def benchmark_forecasts(t: pd.DataFrame, origin: date, grain: str,
                        horizons: tuple[int, ...]) -> list[tuple[str, int, float]]:
    """(model, horizon, total litres) for each benchmark that can be computed."""
    out = []
    bounds = {h: period_bounds(origin, grain, h) for h in horizons}
    days = {h: (e - s).days for h, (s, e) in bounds.items()}
    if grain == "daily":
        week = benchmark_series(t, origin, "weekly")
        daily = benchmark_series(t, origin, "daily")
        p = persistence_value(week)
        for h, (s, _) in bounds.items():
            if p is not None:
                out.append(("persistence", h, p))
            ly = s - timedelta(days=364)
            if ly in daily.index and pd.notna(daily[ly]):
                out.append(("seasonal_naive", h, float(daily[ly])))
        fc = ets_forecast(daily.iloc[-120:], max(horizons), None)
        if fc is not None:
            out += [("ets", h, float(fc[h - 1])) for h in horizons]
        return out

    series = benchmark_series(t, origin, grain)
    p = persistence_value(series)
    steps = max(horizons)
    for h, (s, _) in bounds.items():
        if p is not None:
            out.append(("persistence", h, p * days[h]))
        last_year = add_months(s, -12) if grain == "monthly" else s - timedelta(days=364)
        sn = series.get(last_year)
        if sn is not None and pd.notna(sn):
            out.append(("seasonal_naive", h, float(sn) * days[h]))
    season = 12 if grain == "monthly" else None
    fc = ets_forecast(series, steps, season)
    if fc is not None:
        out += [("ets", h, float(fc[h - 1]) * days[h]) for h in horizons]
    if grain == "monthly":
        fc = sarima_forecast(series, steps, 12)
        if fc is not None:
            out += [("sarima", h, float(fc[h - 1]) * days[h]) for h in horizons]
    return out


@dataclass
class _Ctx:
    """Everything one origin needs; built once per process."""
    source: object
    cfg: EngineConfig
    milk_cfg: MilkConfig
    hist: MilkHistory
    t: pd.DataFrame
    grains: tuple[str, ...]
    score_until: date
    cache: dict


def _score_origin(c: _Ctx, origin: date) -> tuple[list[dict], list[str]]:
    """Error rows and note keys for one origin (origins are independent of each other)."""
    try:
        setup = prepare_milk(c.source, origin, c.milk_cfg, c.hist, c.cache)
    except ValueError:  # no calibration data yet (e.g. first months): skip, but count it
        return [], ["skipped (no usable months for k)"]
    inputs = load_origin_inputs(c.source, origin, c.cfg)
    anchor_k(setup, c.hist.target_before(origin), inputs.state, c.milk_cfg)
    rates = estimate_rates(inputs.rate_inputs, c.cfg)
    H = max(horizon_days(origin, g, max(HORIZONS[g])) for g in c.grains)
    proj = project(inputs.state, rates, H, milk_curve=setup.arrays)
    daily = proj.daily.assign(litres=setup.k * proj.daily["curve_litres"])
    ddates = pd.to_datetime(daily["date"]).dt.date
    notes = [note.split(":")[0] for note in (*setup.notes, *setup.flags)]
    meta = dict(k_source=setup.k_source, curve_source=setup.curve.source,
                flags=";".join(setup.flags))
    rows = []
    for grain in c.grains:
        horizons = HORIZONS[grain]
        preds = {(BASELINE, h): float(daily.loc[(ddates >= s) & (ddates < e), "litres"].sum())
                 for h in horizons for s, e in [period_bounds(origin, grain, h)]}
        for model, h, v in benchmark_forecasts(c.t, origin, grain, horizons):
            preds[(model, h)] = v
        for h in horizons:
            s, e = period_bounds(origin, grain, h)
            if e > c.score_until:
                continue
            act = period_actual(c.t, s, e)
            if act is None:
                continue
            for (model, hh), v in preds.items():
                if hh == h:
                    rows.append(dict(origin=origin, grain=grain, horizon=h, period_start=s,
                                     period_end=e, series=SERIES, model=model, forecast=v,
                                     actual=act[0], source=act[1], **meta))
    return rows, notes


def _milk_ctx(source_factory, snapshots, cfg, milk_cfg, hist, t, grains, score_until) -> _Ctx:
    return _Ctx(SnapshotSource(source_factory(), snapshots), cfg, milk_cfg, hist, t,
                grains, score_until, {})


def run_milk_backtest(
    source,
    origin_grain: str,
    cfg: EngineConfig | None = None,
    milk_cfg: MilkConfig | None = None,
    origins: list[date] | None = None,
    score_until: date = TEST_START,
    progress: Callable[[int, int, date], None] | None = None,
    jobs: int = 1,
    source_factory: Callable[[], object] | None = None,
    block: str = "development",
    prior_errors: pd.DataFrame | None = None,
) -> MilkBacktestResult:
    """``origin_grain`` = "monthly" (scores monthly) or "weekly" (scores weekly and daily).

    The as-of snapshots for all origins are prefetched in a few batched queries.
    ``jobs`` > 1 scores origins in that many processes; each opens its own source with
    ``source_factory`` (a picklable callable, e.g. ``SqlHerdSource.from_env``). Results
    are the same as ``jobs=1`` and in the same order.
    """
    cfg = cfg or EngineConfig()
    milk_cfg = milk_cfg or MilkConfig()
    origins = origins if origins is not None else development_origins(origin_grain)
    check_block(origins, score_until, block)
    if jobs > 1 and source_factory is None:
        raise ValueError("jobs > 1 needs a source_factory so each process opens its own source")
    hist = MilkHistory(cowdays=source.milking_cowdays(DATA_START, score_until),
                       target=source.target_daily(DATA_START, score_until))
    t = _target_frame(hist.target)
    grains = GRAINS_BY_ORIGIN[origin_grain]
    snapshots = prefetch_snapshots(source, origins, cfg)
    serial = (_Ctx(SnapshotSource(source, snapshots), cfg, milk_cfg, hist, t, grains,
                   score_until, {}) if jobs <= 1 else None)
    results = map_origins(origins, _score_origin, _milk_ctx,
                          (source_factory, snapshots, cfg, milk_cfg, hist, t, grains, score_until),
                          jobs=jobs, progress=progress, serial_ctx=serial)
    rows, note_counts = [], {}
    for r, notes in results:
        rows += r
        for key in notes:
            note_counts[key] = note_counts.get(key, 0) + 1
    errors = pd.DataFrame(rows)
    if len(errors):
        errors["error"] = errors["forecast"] - errors["actual"]
        errors = _correct_and_interval(errors, prior_errors)
        errors["model_version"] = MODEL_VERSION
        errors["milk_config"] = milk_cfg.tag()
    notes = pd.DataFrame(sorted(note_counts.items()), columns=["note", "n_origins"])
    return MilkBacktestResult(errors=errors, notes=notes)


def _correct_and_interval(errors: pd.DataFrame, prior: pd.DataFrame | None) -> pd.DataFrame:
    """Bias correction and intervals; ``prior`` (development errors) may supply the
    past errors that a test-block origin is allowed to know."""
    cols = [c for c in errors.columns]
    if prior is not None and len(prior):
        p = prior[prior["model"].isin(errors["model"].unique()) & (prior["model"] != CORRECTED)]
        p = p[[c for c in cols if c in p.columns]].copy()
        for col in ("origin", "period_start", "period_end"):
            p[col] = pd.to_datetime(p[col]).dt.date
        work = pd.concat([p.assign(_prior=True), errors.assign(_prior=False)], ignore_index=True)
    else:
        work = errors.assign(_prior=False)
    corr = bias_corrected(work, base_model=BASELINE, new_model=CORRECTED)
    out = add_intervals(pd.concat([work, corr], ignore_index=True))
    return out[~out["_prior"].astype(bool)].drop(columns="_prior").reset_index(drop=True)


def summarise_milk(errors: pd.DataFrame, by_source: bool = False) -> pd.DataFrame:
    """H1 table: n, MAE, RMSE, bias, MAPE, interval coverage and width per model."""
    if not len(errors):
        return pd.DataFrame()
    keys = ["grain", "horizon", "model"] + (["source"] if by_source else [])
    e = errors.assign(abs_err=errors["error"].abs(), sq=errors["error"] ** 2,
                      ape=(errors["error"].abs() / errors["actual"]).where(errors["actual"] > 0),
                      width=((errors["upper"] - errors["lower"]) / errors["forecast"]).where(errors["forecast"] > 0))
    g = e.groupby(keys)
    out = pd.DataFrame({
        "n": g.size(),
        "mae": g["abs_err"].mean(),
        "rmse": np.sqrt(g["sq"].mean()),
        "bias": g["error"].mean(),
        "mape_pct": 100 * g["ape"].mean(),
        "coverage_pct": 100 * g["covered"].mean(),
        "rel_width": g["width"].mean(),
    }).reset_index()
    return out


def common_periods(errors: pd.DataFrame, models: list[str] | None = None) -> pd.DataFrame:
    """Rows of ``models`` (default: all) restricted to forecasts (grain, horizon, origin,
    period) that every one of those models made, so MAEs compare the same periods."""
    if not len(errors):
        return errors
    models = sorted(set(errors["model"])) if models is None else models
    e = errors[errors["model"].isin(models)]
    keys = ["grain", "horizon", "origin", "period_start"]
    n_models = e.groupby(keys)["model"].transform("nunique")
    return e[n_models == len(models)]
