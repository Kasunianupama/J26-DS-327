"""Official outlook from the frozen model (Step 6): forecasts, intervals, explanations.

``build_outlook`` runs the frozen configuration at one origin and returns three
herd-level tables, matching the ``c1_output`` contract (shared/schemas/pfoi_outlook.py):

* outlook (weekly periods start on the first Monday on/after the origin):
  origin_date, target_period, grain, horizon, series, forecast, lower, upper,
  quality_flag, model_version, core_version;
* attribution: origin_date, target_period, grain, series, factor, contribution, kind,
  model_version, core_version (milk Shapley factors, herd flows, calving split,
  expected mastitis);
* history: the 24 months before the origin (actual milk and herd counts) with a quality
  flag, so charts can show past and future together with gaps shaded.

Intervals come from the model's own backtest errors (development and final test
blocks) whose target period ended before the origin: 5 % / 95 % quantiles of the
relative error at the same grain and series, at the nearest scored horizon at or above
the requested one. ``write_outlook`` replaces the rows of one origin and model version
in ``c1_output``; it is the only code that writes, and only to ``c1_output``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from . import MODEL_VERSION
from .attribution import (
    calving_split, expected_mastitis, explain_forecast_milk, explain_past_milk, herd_flows,
    mastitis_rates, starting_mix,
)
from .backtest_herd import EVENT_SERIES, STOCK_SERIES
from .data import DATA_START, add_months, check_before, load_origin_inputs, month_start
from .config import EngineConfig
from .freeze import FROZEN_ENGINE, FROZEN_MILK, version_label
from .herd_engine import project
from .milk_baseline import MilkConfig, MilkHistory, anchor_k, monthly_target, prepare_milk
from .periods import period_bounds
from .rates import estimate_rates

OUTLOOK_HORIZONS = {"daily": tuple(range(1, 15)), "weekly": tuple(range(1, 14)),
                    "monthly": tuple(range(1, 13))}
HERD_SERIES = ("n_herd", "milking", "calvings", "dry_offs", "real_abortions")
MILK_SERIES = "herd_milk"
LOW_RECORDING_K = 0.6  # recorded milk below 60 % of the curve-implied herd milk
HISTORY_MONTHS = 24
OUTLOOK_COLUMNS = ["origin_date", "target_period", "grain", "horizon", "series", "forecast",
                   "lower", "upper", "quality_flag", "model_version", "core_version"]
ATTRIBUTION_COLUMNS = ["origin_date", "target_period", "grain", "series", "factor",
                       "contribution", "kind", "model_version", "core_version"]
HISTORY_COLUMNS = ["origin_date", "period", "grain", "series", "actual", "quality_flag",
                   "model_version", "core_version"]


def period_starts(origin: date) -> dict[str, date]:
    """Daily and monthly periods start at the origin; weeks at the first Monday on/after it."""
    from datetime import timedelta

    return {"daily": origin, "monthly": origin,
            "weekly": origin + timedelta(days=(7 - origin.weekday()) % 7)}


def interval_table(errors: pd.DataFrame, origin: date) -> pd.DataFrame:
    """5 %/95 % relative-error quantiles per (model, grain, series, horizon), from errors
    whose period ended before ``origin``."""
    if errors is None or not len(errors):
        return pd.DataFrame(columns=["model", "grain", "series", "horizon", "q_lo", "q_hi", "n"])
    e = errors.copy()
    e = e[pd.to_datetime(e["period_end"]).dt.date <= origin]
    e = e[e["forecast"] > 0]
    e["rel"] = e["actual"] / e["forecast"] - 1.0
    g = e.groupby(["model", "grain", "series", "horizon"])["rel"]
    out = pd.DataFrame({"q_lo": g.quantile(0.05), "q_hi": g.quantile(0.95), "n": g.size()}).reset_index()
    return out[out["n"] >= 12]


def _interval(q: pd.DataFrame, model: str, grain: str, series: str, h: int):
    sub = q[(q["model"] == model) & (q["grain"] == grain) & (q["series"] == series)]
    if not len(sub):
        return None
    above = sub[sub["horizon"] >= h]
    row = above.sort_values("horizon").iloc[0] if len(above) else sub.sort_values("horizon").iloc[-1]
    return float(row["q_lo"]), float(row["q_hi"])


@dataclass
class OutputLayer:
    """Corrections applied to the structural forecast after the engine (pfoi-1.1.0).

    Herd series in ``herd_series``: minus the mean past error of ``herd_engine`` (same grain,
    series, horizon; errors ended by the origin, origins in the last 2 years, at least 6),
    as ``error_tools.bias_corrected``. Herd milk: times (1 + level) of the per-horizon
    adaptive filter (``adaptive.level_at``) over ``milk_baseline`` errors ended by the
    origin. A horizon without its own errors uses the next longer backtest horizon (else the
    longest), as the intervals do. Intervals then come from the corrected models' errors.
    """

    herd_bias: dict  # (grain, series, horizon) -> mean error (forecast - actual)
    milk_level: dict  # (grain, horizon) -> adaptive level x
    herd_series: tuple[str, ...]
    herd_model: str = "herd_engine_corrected"
    milk_model: str = "milk_baseline_adaptive"

    @staticmethod
    def _nearest(keys, h: int):
        if not keys:
            return None
        above = [k for k in keys if k >= h]
        return min(above) if above else max(keys)

    def adjust(self, grain: str, series: str, h: int, value: float) -> float:
        if series == MILK_SERIES:
            hz = self._nearest([k for g, k in self.milk_level if g == grain], h)
            return value if hz is None else value * (1.0 + self.milk_level[(grain, hz)])
        if series not in self.herd_series:
            return value
        hz = self._nearest([k for g, sr, k in self.herd_bias if g == grain and sr == series], h)
        return value if hz is None else max(0.0, value - self.herd_bias[(grain, series, hz)])

    def model_for(self, series: str, structural: str) -> str:
        if series == MILK_SERIES:
            return self.milk_model
        return self.herd_model if series in self.herd_series else structural


def build_output_layer(errors: pd.DataFrame | None, origin: date, adaptive_cfg,
                       herd_series: tuple[str, ...]) -> OutputLayer:
    """The correction layer at ``origin`` from backtest errors (only those ended by it)."""
    from .adaptive import level_at
    from .error_tools import CORRECTION_LOOKBACK_DAYS, CORRECTION_MIN_ERRORS

    herd_bias, milk_level = {}, {}
    if errors is not None and len(errors):
        e = errors.copy()
        e["_o"] = pd.to_datetime(e["origin"])
        e["_end"] = pd.to_datetime(e["period_end"])
        o = pd.Timestamp(origin)
        known = e[e["_end"] <= o]
        h = known[(known["model"] == "herd_engine") & known["series"].isin(herd_series)
                  & (known["_o"] >= o - pd.Timedelta(days=CORRECTION_LOOKBACK_DAYS))]
        for (g, sr, hz), grp in h.groupby(["grain", "series", "horizon"]):
            if len(grp) >= CORRECTION_MIN_ERRORS:
                herd_bias[(g, sr, int(hz))] = float((grp["forecast"] - grp["actual"]).mean())
        m = e[(e["model"] == "milk_baseline") & (e["series"] == MILK_SERIES)]
        for (g, hz), grp in m.groupby(["grain", "horizon"]):
            f = grp["forecast"].to_numpy(dtype=float)
            a = grp["actual"].to_numpy(dtype=float)
            with np.errstate(divide="ignore", invalid="ignore"):
                y = np.where(f > 0, np.clip(a / f - 1.0, -0.9, 3.0), np.nan)
            milk_level[(g, int(hz))] = level_at(grp["_end"].to_numpy(), y,
                                                grp["horizon"].to_numpy(dtype=int),
                                                np.datetime64(o), adaptive_cfg)
    return OutputLayer(herd_bias, milk_level, tuple(herd_series))


@dataclass
class FrozenRun:
    """Everything the frozen model computes at one origin (shared by the outlook tables
    and the page document)."""

    origin: date
    hist: MilkHistory
    setup: object
    inputs: object
    rates: object
    proj: object
    daily: pd.DataFrame
    starts: dict
    horizon_days: int
    flag: str
    version: str = MODEL_VERSION  # freeze.version_label of the configuration that ran
    layer: OutputLayer | None = None  # pfoi-1.1.0 corrections; None = structural forecast

    def output(self, grain: str, series: str, h: int, value: float) -> float:
        return value if self.layer is None else self.layer.adjust(grain, series, h, value)

    def interval_model(self, series: str, structural: str) -> str:
        return structural if self.layer is None else self.layer.model_for(series, structural)


def run_frozen(source, origin: date) -> FrozenRun:
    return run_model(source, origin, FROZEN_ENGINE, FROZEN_MILK)


def run_model(source, origin: date, cfg: EngineConfig, mcfg: MilkConfig) -> FrozenRun:
    """The outlook run for any configuration; only pfoi-1.0.0 (``run_frozen``) is published."""
    if origin.day != 1:
        raise ValueError("the outlook origin must be the first day of a month")
    hist = MilkHistory(cowdays=source.milking_cowdays(DATA_START, origin),
                       target=source.target_daily(DATA_START, origin))
    setup = prepare_milk(source, origin, mcfg, hist)
    inputs = load_origin_inputs(source, origin, cfg)
    anchor_k(setup, hist.target_before(origin), inputs.state, mcfg)
    rates = estimate_rates(inputs.rate_inputs, cfg)
    starts = period_starts(origin)
    horizon_days = max((period_bounds(starts[g], g, max(h))[1] - origin).days
                       for g, h in OUTLOOK_HORIZONS.items())
    proj = project(inputs.state, rates, horizon_days, milk_curve=setup.arrays, record_milk_mix=True)
    daily = proj.daily.assign(herd_milk=setup.k * proj.daily["curve_litres"])
    flags = list(setup.flags)
    if setup.k < LOW_RECORDING_K:
        flags.append("low_recording")
    flag = ";".join(sorted(set(flags))) or "ok"
    return FrozenRun(origin, hist, setup, inputs, rates, proj, daily, starts, horizon_days, flag,
                     version_label(cfg, mcfg))


def build_outlook(source, origin: date, errors: pd.DataFrame | None = None,
                  core_version: str | None = None, run: FrozenRun | None = None,
                  ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    run = run or run_frozen(source, origin)
    hist, setup, inputs, rates, proj = run.hist, run.setup, run.inputs, run.rates, run.proj
    daily, starts, horizon_days, flag = run.daily, run.starts, run.horizon_days, run.flag
    dates = pd.to_datetime(daily["date"]).dt.date
    q = interval_table(errors, origin)
    meta = dict(model_version=run.version, core_version=core_version)

    rows = []
    for grain, horizons in OUTLOOK_HORIZONS.items():
        for h in horizons:
            s, e = period_bounds(starts[grain], grain, h)
            part = daily.loc[(dates >= s) & (dates < e)]
            if len(part) != (e - s).days:
                continue
            values = {MILK_SERIES: ("milk_baseline", float(part["herd_milk"].sum()))}
            for col in HERD_SERIES:
                v = float(part[col].mean()) if col in STOCK_SERIES else float(part[col].sum())
                values[col] = ("herd_engine", v)
            for series, (model, v) in values.items():
                v = run.output(grain, series, h, v)
                iv = _interval(q, run.interval_model(series, model), grain, series, h)
                lo, hi = (v * (1 + iv[0]), v * (1 + iv[1])) if iv else (np.nan, np.nan)
                rows.append(dict(origin_date=origin, target_period=s, grain=grain, horizon=h,
                                 series=series, forecast=v, lower=max(lo, 0.0) if iv else np.nan,
                                 upper=hi, quality_flag=flag, **meta))
    outlook = pd.DataFrame(rows, columns=OUTLOOK_COLUMNS)

    # explanations
    tm = monthly_target(hist.target_before(origin))
    good = tm[tm["share"] >= 0.8]
    actual = pd.DataFrame({"litres_per_day": good["litres"] / good["ok_days"], "source": good["source"]})
    cowdays = hist.cowdays_before(month_start(origin), origin)
    milk_past = explain_past_milk(cowdays, actual, setup.curve, origin, months=12)
    milk_future = explain_forecast_milk(proj.milk_mix, list(dates), setup.k, setup.curve,
                                        starting_mix(inputs.state, origin), origin)
    milk_attr = pd.concat([milk_past, milk_future], ignore_index=True)
    milk_attr = milk_attr[milk_attr["factor"] != "skipped"]
    herd_attr = herd_flows(daily, origin).assign(kind="forecast")
    split = calving_split(inputs.state, rates, horizon_days, origin).assign(kind="forecast")
    health = check_before(source.health_months(DATA_START, month_start(origin)), origin, "health_months")
    md = check_before(source.exposure(DATA_START, month_start(origin)), origin, "exposure")
    md = md[md["state"] == "milking"].groupby("month")["animal_days"].sum()
    mast = expected_mastitis(daily, mastitis_rates(health, md, origin), origin).assign(kind="forecast")
    attribution = pd.concat([milk_attr, herd_attr, split, mast], ignore_index=True)
    attribution = attribution[attribution["target_period"] < add_months(origin, 12)]
    for k, v in meta.items():
        attribution[k] = v
    attribution = attribution[ATTRIBUTION_COLUMNS]

    # history for charts
    hrows = []
    start = add_months(month_start(origin), -HISTORY_MONTHS)
    for m, r in tm.iterrows():
        if not start <= m < month_start(origin):
            continue
        ok = r["share"] >= 0.8 and r["source"] is not None
        hrows.append(dict(origin_date=origin, period=m, grain="monthly", series=MILK_SERIES,
                          actual=float(r["litres"] / r["ok_days"] * r["days"]) if ok else np.nan,
                          quality_flag="ok" if ok else ("gap" if r["share"] == 0 else "partial"), **meta))
    panel = source.panel_daily(start, month_start(origin))
    panel["month"] = [d.replace(day=1) for d in pd.to_datetime(panel["date"]).dt.date]
    for m, g in panel.groupby("month"):
        for col in HERD_SERIES:
            v = float(g[col].mean()) if col in STOCK_SERIES else float(g[col].sum())
            hrows.append(dict(origin_date=origin, period=m, grain="monthly", series=col, actual=v,
                              quality_flag="ok", **meta))
    history = pd.DataFrame(hrows, columns=HISTORY_COLUMNS)
    return outlook, attribution, history


def write_outlook(engine, outlook: pd.DataFrame, attribution: pd.DataFrame,
                  history: pd.DataFrame, schema: str = "c1_output") -> dict[str, int]:
    """Replace this origin's rows (same model_version) in c1_output; returns row counts."""
    from sqlalchemy import text

    origin = outlook["origin_date"].iloc[0]
    version = outlook["model_version"].iloc[0]
    counts = {}
    with engine.begin() as conn:
        for table, frame in (("outlook", outlook), ("attribution", attribution), ("history", history)):
            conn.execute(text(f"DELETE FROM {schema}.{table} "
                              "WHERE origin_date = :o AND model_version = :v"), {"o": origin, "v": version})
            records = frame.astype(object).where(frame.notna(), None).to_dict("records")
            if records:
                cols = ", ".join(frame.columns)
                params = ", ".join(f":{c}" for c in frame.columns)
                conn.execute(text(f"INSERT INTO {schema}.{table} ({cols}) VALUES ({params})"), records)
            counts[table] = len(records)
    return counts


def write_run_document(engine, document: dict, schema: str = "c1_output") -> None:
    """Replace the page document of this origin and model version."""
    import json

    from sqlalchemy import text

    params = {"o": document["origin_date"], "v": document["model_version"],
              "c": document.get("core_version"), "d": json.dumps(document)}
    with engine.begin() as conn:
        conn.execute(text(f"DELETE FROM {schema}.run_document WHERE origin_date = :o AND model_version = :v"),
                     params)
        conn.execute(text(f"INSERT INTO {schema}.run_document (origin_date, model_version, core_version, "
                          "document) VALUES (:o, :v, :c, CAST(:d AS jsonb))"), params)
