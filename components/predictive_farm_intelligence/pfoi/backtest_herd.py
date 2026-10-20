"""Rolling-origin backtest of the herd engine (development block only).

At each origin the inputs are reloaded with only facts before the origin, rates are
re-estimated, and the herd is projected. Forecasts are compared with the actual
herd-level daily panel, aggregated to the same periods. Persistence is reported
alongside as a reference. Targets on or after 2024-01-01 (final test block) are
never scored here; the final test is run once, on the frozen model, in Step 6.

All outputs are herd-level aggregates (one value per origin x period x series).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable

import numpy as np
import pandas as pd

from .freeze import version_label
from .config import EngineConfig
from .data import (
    DATA_START, HerdSource, SnapshotSource, load_origin_inputs, month_start, prefetch_snapshots,
)
from .parallel import map_origins
from .herd_engine import project
from .periods import HORIZONS, aggregate, check_origin, horizon_days, period_bounds
from .benchmarks import ets_forecast, sarima_forecast
from .error_tools import bias_corrected as _bias_corrected
from .rates import estimate_rates

DEV_FIRST_ORIGIN = date(2017, 1, 1)
TEST_START = date(2024, 1, 1)

STOCK_SERIES = (
    "n_herd", "calves", "heifers_open", "heifers_pregnant", "milking", "dry_open", "dry_pregnant",
)
EVENT_SERIES = (
    "calvings", "dry_offs", "ais", "real_abortions", "deaths", "culls", "sales", "births",
    "external_entries",
)
KEY_SERIES = ("milking", "n_herd", "calvings", "real_abortions")
# Scored at monthly grain only, against core.state_transition_month (diagnostic).
HEIFER_CALVINGS = "calvings_heifer"
CORRECTED = "herd_engine_corrected"
# Monthly series also benchmarked with ETS and SARIMA (statsmodels).
TS_BENCHMARK_SERIES = ("n_herd", "milking", "calvings")


def bias_corrected(errors: pd.DataFrame, **kw) -> pd.DataFrame:
    return _bias_corrected(errors, base_model="herd_engine", new_model=CORRECTED, **kw)


def ts_benchmarks(past: pd.DataFrame, origin: date, horizons: tuple[int, ...]) -> pd.DataFrame:
    """ETS and SARIMA on monthly means (stocks) or daily rates (events) before the origin."""
    p = past.copy()
    p["month"] = [d.replace(day=1) for d in pd.to_datetime(p["date"]).dt.date]
    months = p.groupby("month")
    rows = []
    steps = max(horizons)
    for col in TS_BENCHMARK_SERIES:
        series = months[col].mean()  # stock: mean animals; event: mean per day
        series = series[series.index < origin]
        for model, fn in (("ets", lambda y: ets_forecast(y, steps, 12)),
                          ("sarima", lambda y: sarima_forecast(y, steps, 12))):
            fc = fn(series)
            if fc is None:
                continue
            for h in horizons:
                start, end = period_bounds(origin, "monthly", h)
                v = fc[h - 1] * ((end - start).days if col in EVENT_SERIES else 1)
                rows.append((h, start, col, float(v), model))
    return pd.DataFrame(rows, columns=["horizon", "period_start", "series", "value", "model"])


def check_block(origins: list[date], score_until: date, block: str) -> None:
    """Development scores nothing from 2024-01; the test block scores only from 2024-01."""
    from .freeze import DATA_END

    if block == "development":
        if score_until > TEST_START or any(o >= TEST_START for o in origins):
            raise ValueError("the final test block (2024-01 onward) is not scored in development")
    elif block == "test":
        if any(o < TEST_START for o in origins) or score_until > DATA_END:
            raise ValueError("test-block origins start at 2024-01 and targets end at the data end")
    elif block == "posthoc":
        # Explicit research replay, separate from the run-once frozen test contract.
        if any(o < TEST_START or o >= score_until for o in origins) or score_until <= TEST_START:
            raise ValueError("posthoc origins must start in 2024 and precede the data cutoff")
    else:
        raise ValueError(f"unknown block {block!r}")


def development_origins(grain: str, every: int = 1) -> list[date]:
    if grain == "monthly":
        out, d = [], DEV_FIRST_ORIGIN
        while d < TEST_START:
            out.append(d)
            d = date(d.year + d.month // 12, d.month % 12 + 1, 1)
        return out[::every]
    d = DEV_FIRST_ORIGIN + timedelta(days=(7 - DEV_FIRST_ORIGIN.weekday()) % 7)
    out = []
    while d < TEST_START:
        out.append(d)
        d += timedelta(days=7)
    return out[::every]


def persistence(actuals: pd.DataFrame, origin: date, grain: str,
                horizons: tuple[int, ...]) -> pd.DataFrame:
    """Stocks: last known day. Events: daily mean of the previous period x period days."""
    dates = pd.to_datetime(actuals["date"]).dt.date
    last = actuals.loc[dates == origin - timedelta(days=1)]
    if grain == "monthly":
        prev_start = date(origin.year - (origin.month == 1), (origin.month - 2) % 12 + 1, 1)
    else:
        prev_start = origin - timedelta(days=7)
    prev = actuals.loc[(dates >= prev_start) & (dates < origin)]
    rows = []
    if not len(last) or not len(prev):
        return pd.DataFrame(rows, columns=["horizon", "period_start", "series", "value"])
    for h in horizons:
        start, end = period_bounds(origin, grain, h)
        days = (end - start).days
        for col in STOCK_SERIES:
            rows.append((h, start, col, float(last[col].iloc[0])))
        for col in EVENT_SERIES:
            rows.append((h, start, col, float(prev[col].mean()) * days))
    return pd.DataFrame(rows, columns=["horizon", "period_start", "series", "value"])


@dataclass
class BacktestResult:
    errors: pd.DataFrame  # origin, grain, horizon, period_start, series, model, forecast, actual, error
    notes: pd.DataFrame  # note, n_origins


@dataclass
class _HerdCtx:
    """Everything one origin needs; built once per process."""
    source: object
    grain: str
    cfg: EngineConfig
    actuals: pd.DataFrame
    heifer_calvings: pd.Series | None
    score_until: date

    def __post_init__(self):
        self.act_dates = pd.to_datetime(self.actuals["date"]).dt.date


def _herd_ctx(source_factory, snapshots, grain, cfg, actuals, heifer_calvings,
              score_until) -> _HerdCtx:
    return _HerdCtx(SnapshotSource(source_factory(), snapshots), grain, cfg, actuals,
                    heifer_calvings, score_until)


def _score_herd_origin(c: _HerdCtx, origin: date) -> tuple[list[pd.DataFrame], list[str]]:
    """Merged forecast/actual frames and note keys for one origin."""
    grain, horizons = c.grain, HORIZONS[c.grain]
    check_origin(origin, grain)
    H = horizon_days(origin, grain, max(horizons))
    inputs = load_origin_inputs(c.source, origin, c.cfg)
    rates = estimate_rates(inputs.rate_inputs, c.cfg)
    notes = [note.split(":")[0] for note in (*inputs.notes, *rates.notes)]
    proj = project(inputs.state, rates, H)
    fc = aggregate(proj.daily, origin, grain, horizons, STOCK_SERIES,
                   EVENT_SERIES + ((HEIFER_CALVINGS,) if c.heifer_calvings is not None else ()))
    future = c.actuals.loc[(c.act_dates >= origin) & (c.act_dates < c.score_until)]
    act = aggregate(future, origin, grain, horizons, STOCK_SERIES, EVENT_SERIES)
    if not len(act):
        return [], notes
    act = act.rename(columns={"value": "actual"})
    past = c.actuals.loc[c.act_dates < origin]
    pers = persistence(past, origin, grain, horizons)
    if c.heifer_calvings is not None:
        act, pers = _add_heifer_calvings(act, pers, c.heifer_calvings, origin)
    preds = [("herd_engine", fc[["horizon", "period_start", "series", "value"]]),
             ("persistence", pers)]
    if grain == "monthly":
        ts = ts_benchmarks(past, origin, horizons)
        preds += [(m, g.drop(columns="model")) for m, g in ts.groupby("model")]
    frames = []
    for model, pred in preds:
        m = act.merge(pred.rename(columns={"value": "forecast"}),
                      on=["horizon", "period_start", "series"])
        m["origin"] = origin
        m["model"] = model
        frames.append(m)
    return frames, notes


def run_backtest(
    source: HerdSource,
    grain: str,
    cfg: EngineConfig | None = None,
    origins: list[date] | None = None,
    score_until: date = TEST_START,
    progress: Callable[[int, int, date], None] | None = None,
    block: str = "development",
    prior_errors: pd.DataFrame | None = None,
    jobs: int = 1,
    source_factory: Callable[[], HerdSource] | None = None,
) -> BacktestResult:
    """The as-of snapshots for all origins are prefetched in a few batched queries.
    ``jobs`` > 1 scores origins in that many processes; each opens its own source with
    ``source_factory`` (picklable, e.g. ``SqlHerdSource.from_env``). Results are the
    same as ``jobs=1`` and in the same order."""
    cfg = cfg or EngineConfig()
    origins = origins if origins is not None else development_origins(grain)
    check_block(origins, score_until, block)
    for origin in origins:
        check_origin(origin, grain)
    if jobs > 1 and source_factory is None:
        raise ValueError("jobs > 1 needs a source_factory so each process opens its own source")
    actuals = source.panel_daily(DATA_START, score_until)
    heifer_calvings = None
    if grain == "monthly":
        tr = source.transitions(DATA_START, month_start(score_until))
        tr = tr[(tr["from_state"] == "heifer_pregnant") & (tr["to_state"] == "milking")]
        heifer_calvings = tr.groupby("month")["n_moved"].sum()
        heifer_calvings.index = [pd.Timestamp(m).date() for m in heifer_calvings.index]

    snapshots = prefetch_snapshots(source, origins, cfg)
    serial = (_HerdCtx(SnapshotSource(source, snapshots), grain, cfg, actuals, heifer_calvings,
                       score_until) if jobs <= 1 else None)
    results = map_origins(origins, _score_herd_origin, _herd_ctx,
                          (source_factory, snapshots, grain, cfg, actuals, heifer_calvings,
                           score_until),
                          jobs=jobs, progress=progress, serial_ctx=serial)
    frames, note_counts = [], {}
    for f, notes in results:
        frames += f
        for key in notes:
            note_counts[key] = note_counts.get(key, 0) + 1

    errors = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["horizon", "period_start", "period_end", "series", "actual", "forecast",
                 "origin", "model"])
    errors["grain"] = grain
    errors["error"] = errors["forecast"] - errors["actual"]
    errors = pd.concat([errors, _corrected_with_prior(errors, prior_errors)], ignore_index=True)
    errors["model_version"] = version_label(cfg)
    errors = errors[["origin", "grain", "horizon", "period_start", "period_end", "series",
                     "model", "forecast", "actual", "error", "model_version"]]
    notes = pd.DataFrame(sorted(note_counts.items()), columns=["note", "n_origins"])
    return BacktestResult(errors=errors, notes=notes)


def _corrected_with_prior(errors: pd.DataFrame, prior: pd.DataFrame | None) -> pd.DataFrame:
    """Bias correction that may also learn from earlier (development) errors."""
    if prior is None or not len(prior):
        return bias_corrected(errors)
    p = prior[prior["model"] == "herd_engine"].copy()
    p["_prior"] = True
    both = pd.concat([p, errors.assign(_prior=False)], ignore_index=True)
    for col in ("origin", "period_start", "period_end"):
        both[col] = pd.to_datetime(both[col]).dt.date
    out = bias_corrected(both)
    return out[~out["_prior"].astype(bool)].drop(columns="_prior")


def _add_heifer_calvings(act: pd.DataFrame, pers: pd.DataFrame, monthly: pd.Series,
                         origin: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Actual heifer calvings per month (transition table) and their persistence value."""
    starts = act[["horizon", "period_start", "period_end"]].drop_duplicates()
    rows = [(r.horizon, r.period_start, r.period_end, HEIFER_CALVINGS, float(monthly[r.period_start]))
            for r in starts.itertuples(index=False) if r.period_start in monthly.index]
    if rows:
        act = pd.concat([act, pd.DataFrame(rows, columns=act.columns)], ignore_index=True)
    prev = date(origin.year - (origin.month == 1), (origin.month - 2) % 12 + 1, 1)
    if prev in monthly.index and len(pers):
        prow = [(h, ps, HEIFER_CALVINGS, float(monthly[prev]))
                for h, ps in pers[["horizon", "period_start"]].drop_duplicates().itertuples(index=False)]
        pers = pd.concat([pers, pd.DataFrame(prow, columns=pers.columns)], ignore_index=True)
    return act, pers


def summarise(errors: pd.DataFrame) -> pd.DataFrame:
    """MAE, RMSE and bias (forecast - actual) by grain x horizon x series x model."""
    if not len(errors):
        return pd.DataFrame(columns=["grain", "horizon", "series", "model", "n", "mae", "rmse", "bias"])
    g = errors.groupby(["grain", "horizon", "series", "model"])["error"]
    out = g.agg(
        n="count",
        mae=lambda e: float(np.abs(e).mean()),
        rmse=lambda e: float(np.sqrt((e ** 2).mean())),
        bias="mean",
    ).reset_index()
    return out
