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

from . import MODEL_VERSION
from .config import EngineConfig
from .data import DATA_START, HerdSource, load_origin_inputs, month_start
from .herd_engine import project
from .periods import HORIZONS, aggregate, check_origin, horizon_days, period_bounds
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
CORRECTION_LOOKBACK_DAYS = 730
CORRECTION_MIN_ERRORS = 6


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


def run_backtest(
    source: HerdSource,
    grain: str,
    cfg: EngineConfig | None = None,
    origins: list[date] | None = None,
    score_until: date = TEST_START,
    progress: Callable[[int, int, date], None] | None = None,
) -> BacktestResult:
    cfg = cfg or EngineConfig()
    horizons = HORIZONS[grain]
    origins = origins if origins is not None else development_origins(grain)
    if score_until > TEST_START or any(o >= TEST_START for o in origins):
        raise ValueError("the final test block (2024-01 onward) is not scored in development")
    actuals = source.panel_daily(DATA_START, score_until)
    act_dates = pd.to_datetime(actuals["date"]).dt.date
    heifer_calvings = None
    if grain == "monthly":
        tr = source.transitions(DATA_START, month_start(score_until))
        tr = tr[(tr["from_state"] == "heifer_pregnant") & (tr["to_state"] == "milking")]
        heifer_calvings = tr.groupby("month")["n_moved"].sum()
        heifer_calvings.index = [pd.Timestamp(m).date() for m in heifer_calvings.index]

    frames, note_counts = [], {}
    for i, origin in enumerate(origins):
        check_origin(origin, grain)
        if progress:
            progress(i, len(origins), origin)
        H = horizon_days(origin, grain, max(horizons))
        inputs = load_origin_inputs(source, origin, cfg)
        rates = estimate_rates(inputs.rate_inputs, cfg)
        for note in (*inputs.notes, *rates.notes):
            key = note.split(":")[0]
            note_counts[key] = note_counts.get(key, 0) + 1
        proj = project(inputs.state, rates, H)
        fc = aggregate(proj.daily, origin, grain, horizons, STOCK_SERIES,
                       EVENT_SERIES + ((HEIFER_CALVINGS,) if heifer_calvings is not None else ()))
        future = actuals.loc[(act_dates >= origin) & (act_dates < score_until)]
        act = aggregate(future, origin, grain, horizons, STOCK_SERIES, EVENT_SERIES)
        if not len(act):
            continue
        act = act.rename(columns={"value": "actual"})
        past = actuals.loc[act_dates < origin]
        pers = persistence(past, origin, grain, horizons)
        if heifer_calvings is not None:
            act, pers = _add_heifer_calvings(act, pers, heifer_calvings, origin)
        for model, pred in (
            ("herd_engine", fc[["horizon", "period_start", "series", "value"]]),
            ("persistence", pers),
        ):
            m = act.merge(pred.rename(columns={"value": "forecast"}),
                          on=["horizon", "period_start", "series"])
            m["origin"] = origin
            m["model"] = model
            frames.append(m)

    errors = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["horizon", "period_start", "period_end", "series", "actual", "forecast",
                 "origin", "model"])
    errors["grain"] = grain
    errors["error"] = errors["forecast"] - errors["actual"]
    errors = pd.concat([errors, bias_corrected(errors)], ignore_index=True)
    errors["model_version"] = MODEL_VERSION
    errors = errors[["origin", "grain", "horizon", "period_start", "period_end", "series",
                     "model", "forecast", "actual", "error", "model_version"]]
    notes = pd.DataFrame(sorted(note_counts.items()), columns=["note", "n_origins"])
    return BacktestResult(errors=errors, notes=notes)


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


def bias_corrected(errors: pd.DataFrame,
                   lookback_days: int = CORRECTION_LOOKBACK_DAYS,
                   min_errors: int = CORRECTION_MIN_ERRORS) -> pd.DataFrame:
    """Engine forecasts minus the engine's own mean past error (same grain, series, horizon).

    Only errors whose target period had ended by the origin, from origins in the
    previous ``lookback_days``, are used, so nothing after the origin is seen. With
    fewer than ``min_errors`` such errors the raw forecast is kept.
    """
    eng = errors[errors["model"] == "herd_engine"]
    out = []
    for _, g in eng.groupby(["grain", "series", "horizon"]):
        g = g.sort_values("origin")
        origins = pd.to_datetime(g["origin"]).to_numpy()
        ends = pd.to_datetime(g["period_end"]).to_numpy()
        err = g["error"].to_numpy(dtype=float)
        corr = np.zeros(len(g))
        lookback = np.timedelta64(lookback_days, "D")
        for i, o in enumerate(origins):
            mask = (ends <= o) & (origins >= o - lookback)
            if mask.sum() >= min_errors:
                corr[i] = err[mask].mean()
        c = g.copy()
        c["forecast"] = g["forecast"] - corr
        c["error"] = c["forecast"] - c["actual"]
        c["model"] = CORRECTED
        out.append(c)
    return pd.concat(out, ignore_index=True) if out else eng.iloc[0:0]


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
