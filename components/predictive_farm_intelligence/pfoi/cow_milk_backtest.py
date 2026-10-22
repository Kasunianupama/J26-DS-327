"""Rolling-origin backtest of the pfoi-1.8.0-dev milk predictor (herd and cow level).

At every monthly origin *o* the selected Notebook 6 predictor is refitted on records
strictly before *o* (gap excluded, events cut at *o*), and the origin cohort is
forecast for ``max_months`` months with every feature frozen at *o*. Outcomes are read
only after the forecasts are fixed. Everything returned is aggregate (per origin and
period, or per origin and horizon); no animal identifier leaves this module.

Herd milk forecasts (monthly periods, horizon 1 = the origin month):

- ``pfoi-1.8.0-dev``: sum over days of projected milking cows x cohort mean predicted
  yield. Milking cows = pfoi-1.2.0-dev's herd backtest forecast for that origin and
  month (its monthly mean, constant within the month), i.e. the forecast the page
  would have had.
- ``pfoi-1.8.0-dev_oracle_milking``: the same yields x the **recorded** milking cows.
  Diagnostic only (uses outcomes): it isolates the yield model from herd-count error.
- ``persistence``: mean scoreable herd milk of the 28 days before *o* x days.
- ``seasonal_naive``: the same calendar month a year earlier, if scoreable.
- ``pfoi-1.2.0-dev`` (optional): rows of its own milk backtest error file.

Actual = the clean placeholder-free daily target summed over the month, scored only
when every day is scoreable. Comparisons use **identical** (origin, period) sets.

Cow level: the cohort's predicted yield vs its own recorded yields after *o*, pooled
per origin and horizon (sums only): WAPE over recorded cow-days.

Intervals: for origin *o*, 5-95 % conformal log-error quantiles per horizon from the
1.8.0-dev errors of earlier origins whose period ended before *o*
(``calibration_from_errors``); coverage is then checked on *o* itself. Cells with
fewer than ``min_samples`` past errors give no interval (counted, never guessed).
"""
from __future__ import annotations

import math
import time
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .cow_accuracy import MIN_COWS_PER_DAY
from .cow_milk_predictor import (NEURAL_MILK_VERSION, fit_predictor, inference_input,
                                 origin_cohort, origin_history, origin_safe_events,
                                 supported_end)
from .cow_torch_outlook import calibration_from_errors

MODEL = NEURAL_MILK_VERSION
ORACLE = f"{NEURAL_MILK_VERSION}_oracle_milking"
SELECTION_END = date(2021, 11, 28)  # Notebook 6 validation end (user-supplied, 2026-10-22)


def _month_bounds(origin: date, h: int) -> tuple[date, date]:
    return supported_end(origin, h - 1) if h > 1 else origin, supported_end(origin, h)


def monthly_milking_projection(herd_errors: pd.DataFrame, model: str = "herd_engine"
                               ) -> dict[tuple[date, int], float]:
    """(origin, horizon) -> projected mean milking cows, from a herd backtest error file."""
    e = herd_errors[(herd_errors["series"] == "milking") & (herd_errors["model"] == model)
                    & (herd_errors["grain"] == "monthly")]
    if e.empty:
        found = herd_errors.groupby(["grain", "series", "model"]).size()
        raise ValueError(f"no monthly milking rows for model {model!r}; available "
                         f"(grain, series, model) counts: {found.to_dict()}")
    o = pd.to_datetime(e["origin"]).dt.date
    return {(oo, int(h)): float(f) for oo, h, f in zip(o, e["horizon"], e["forecast"])}


def backtest_origin(raw: pd.DataFrame, events: dict | None, target: pd.DataFrame,
                    milking_actual: pd.Series, projection: dict, origin: date, selection,
                    *, max_months: int = 12, cohort_days: int = 28, fit_fn=None,
                    device: str = "cpu") -> tuple[list[dict], list[dict], dict]:
    """Forecast rows, cow-level sums and an origin audit (all aggregate) for one origin."""
    end = supported_end(origin, max_months)
    hist = origin_history(raw, origin, selection.data_scope)
    future, counts = origin_cohort(hist, origin, end, cohort_days)
    audit = {"origin": origin.isoformat(), **counts, "status": "ok"}
    t = target.set_index("date")
    rows, cows = [], []

    def benchmarks(h, s, e):
        days = [s + timedelta(days=i) for i in range((e - s).days)]
        actual_ok = all(d in t.index and bool(t.at[d, "is_scoreable"]) for d in days)
        actual = float(sum(t.at[d, "target_litres"] for d in days)) if actual_ok else None
        recent = t[(t.index >= origin - timedelta(days=28)) & (t.index < origin)
                   & t["is_scoreable"].astype(bool)]["target_litres"]
        persist = float(recent.mean()) * len(days) if len(recent) >= 7 else None
        ly_s, ly_e = date(s.year - 1, s.month, 1), date(e.year - 1, e.month, 1)
        ly = [ly_s + timedelta(days=i) for i in range((ly_e - ly_s).days)]
        ly_ok = all(d in t.index and bool(t.at[d, "is_scoreable"]) for d in ly)
        seasonal = float(sum(t.at[d, "target_litres"] for d in ly)) if ly_ok else None
        return days, actual, persist, seasonal

    def row(model, h, s, e, forecast, actual, **extra):
        return {"origin": origin.isoformat(), "grain": "monthly", "horizon": h,
                "period_start": s.isoformat(), "period_end": e.isoformat(),
                "series": "herd_milk", "model": model, "forecast": forecast,
                "actual": actual, **extra}

    if counts["cohort_cows"] < MIN_COWS_PER_DAY:
        audit["status"] = "no_cohort"
        for h in range(1, max_months + 1):
            s, e = _month_bounds(origin, h)
            _, actual, persist, seasonal = benchmarks(h, s, e)
            rows += [row(MODEL, h, s, e, None, actual, reason="no_cohort"),
                     row("persistence", h, s, e, persist, actual),
                     row("seasonal_naive", h, s, e, seasonal, actual)]
        return rows, cows, audit

    t0 = time.perf_counter()
    allr = inference_input(hist, future, origin)
    _, frame, final = fit_predictor(allr, origin_safe_events(events, origin), origin,
                                    selection, device=device, fit_fn=fit_fn)
    audit["fit_seconds"] = round(time.perf_counter() - t0, 1)
    fut = (frame["is_future"].astype(bool) & frame["score_eligible"].astype(bool)).to_numpy()
    d = pd.DataFrame({"date": pd.to_datetime(frame["date"]).dt.date.to_numpy()[fut],
                      "animal": frame["animal"].to_numpy()[fut],
                      "pred": np.asarray(final, float)[fut]})
    per_day = d.groupby("date").agg(yield_per_cow=("pred", "mean"), cohort=("pred", "size"))

    # Outcomes, read only now: the cohort's own recorded yields after the origin.
    later = raw[(pd.to_datetime(raw["date"]) >= pd.Timestamp(origin))
                & (pd.to_datetime(raw["date"]) < pd.Timestamp(end))]
    later = origin_history(later.assign(date=pd.to_datetime(later["date"])), end,
                           selection.data_scope)
    rec = later.rename(columns={"cow_id": "animal"})[["animal", "date", "litres"]].copy()
    rec["date"] = pd.to_datetime(rec["date"]).dt.date
    rec["animal"] = pd.to_numeric(rec["animal"]).astype("int64")
    m = d.merge(rec, on=["animal", "date"], how="inner")

    for h in range(1, max_months + 1):
        s, e = _month_bounds(origin, h)
        days, actual, persist, seasonal = benchmarks(h, s, e)
        y = per_day.reindex(days)
        cohort_min = int(y["cohort"].fillna(0).min())
        ok = cohort_min >= MIN_COWS_PER_DAY
        n_proj = projection.get((origin, h))
        ybar = y["yield_per_cow"].to_numpy(float)
        fc = float(n_proj * np.nansum(ybar)) if ok and n_proj is not None else None
        n_act = milking_actual.reindex(days)
        oracle = (float(np.sum(n_act.to_numpy(float) * ybar))
                  if ok and n_act.notna().all() else None)
        ypc_actual = (actual / float(n_act.sum())) if actual is not None and n_act.notna().all() \
            and n_act.sum() > 0 else None
        extra = {"cohort_cows_min": cohort_min,
                 "cohort_share_of_milking": (round(cohort_min / n_proj, 4)
                                             if n_proj else None),
                 "yield_per_cow_forecast": round(float(np.nanmean(ybar)), 4) if ok else None,
                 "yield_per_cow_actual": round(ypc_actual, 4) if ypc_actual else None,
                 "reason": None if ok and n_proj is not None else
                 ("cohort_below_minimum" if not ok else "no_projected_milking")}
        rows += [row(MODEL, h, s, e, fc, actual, **extra),
                 row(ORACLE, h, s, e, oracle, actual, diagnostic="uses recorded milking cows"),
                 row("persistence", h, s, e, persist, actual),
                 row("seasonal_naive", h, s, e, seasonal, actual)]
        part = m[(m["date"] >= s) & (m["date"] < e)]
        if len(part):
            err = part["pred"] - part["litres"]
            cows.append({"origin": origin.isoformat(), "horizon": h, "cow_days": int(len(part)),
                         "cows": int(part["animal"].nunique()),
                         "abs_error_sum": float(err.abs().sum()), "error_sum": float(err.sum()),
                         "squared_error_sum": float((err ** 2).sum()),
                         "actual_sum": float(part["litres"].sum())})
    return rows, cows, audit


def add_reference(errors: pd.DataFrame, reference: pd.DataFrame, model: str,
                  label: str = "pfoi-1.2.0-dev") -> pd.DataFrame:
    """Append another model's monthly herd-milk backtest rows under ``label``."""
    r = reference[(reference["model"] == model) & (reference["grain"] == "monthly")]
    if r.empty:
        found = reference.groupby(["grain", "model"]).size()
        raise ValueError(f"no monthly rows for {model!r}; available: {found.to_dict()}")
    r = r.assign(origin=pd.to_datetime(r["origin"]).dt.date.astype(str),
                 period_start=pd.to_datetime(r["period_start"]).dt.date.astype(str),
                 model=label, reference_actual=r["actual"])
    keys = errors[errors["model"] == MODEL][["origin", "horizon", "period_start", "actual"]]
    r = r.drop(columns=["actual"]).merge(keys, on=["origin", "horizon", "period_start"], how="inner")
    cols = ["origin", "grain", "horizon", "period_start", "series", "model", "forecast", "actual",
            "reference_actual"]
    return pd.concat([errors, r[[c for c in cols if c in r]]], ignore_index=True)


def add_intervals(errors: pd.DataFrame, level: float = 0.90, min_samples: int = 8,
                  model: str = MODEL) -> pd.DataFrame:
    """Out-of-sample 5-95 % ranges for ``model`` from its own earlier errors only."""
    e = errors.copy()
    e["lower"], e["upper"], e["interval_n"] = np.nan, np.nan, 0
    own = e[(e["model"] == model) & e["forecast"].notna() & e["actual"].notna()]
    for o in sorted(e.loc[e["model"] == model, "origin"].unique()):
        od = date.fromisoformat(o)
        cells = {c.horizon: c for c in calibration_from_errors(own, od, level, min_samples)}
        idx = e.index[(e["model"] == model) & (e["origin"] == o) & e["forecast"].notna()]
        for i in idx:
            c = cells.get(int(e.at[i, "horizon"]))
            if c is not None:
                f = float(e.at[i, "forecast"])
                e.loc[i, ["lower", "upper", "interval_n"]] = [f * math.exp(c.q_lo),
                                                             f * math.exp(c.q_hi), c.n]
    return e


def summarise(errors: pd.DataFrame, models: list[str] | None = None,
              by: tuple[str, ...] = ("horizon",)) -> pd.DataFrame:
    """MAE, RMSE, bias, WAPE (= sum|error| / sum actual), accuracy (= 100 - WAPE) and
    5-95 % coverage on the (origin, period) cells that **every** listed model forecast."""
    e = errors[errors["actual"].notna()].copy()
    models = models or sorted(e["model"].unique())
    e = e[e["model"].isin(models)]
    have = e[e["forecast"].notna()].groupby(["origin", "horizon"])["model"].nunique()
    common = have[have == len(models)].index
    e = e.set_index(["origin", "horizon"]).loc[lambda x: x.index.isin(common)].reset_index()
    if e.empty:
        return pd.DataFrame()
    e["error"] = e["forecast"] - e["actual"]
    rows = []
    for key, g in e.groupby(["model", *by]):
        key = key if isinstance(key, tuple) else (key,)
        cov = g.dropna(subset=["lower", "upper"]) if "lower" in g else g.iloc[0:0]
        rows.append({**dict(zip(["model", *by], key)), "n": len(g),
                     "mae": g["error"].abs().mean(), "rmse": float(np.sqrt((g["error"] ** 2).mean())),
                     "bias": g["error"].mean(),
                     "wape_pct": 100 * g["error"].abs().sum() / g["actual"].sum(),
                     "accuracy_pct": 100 - 100 * g["error"].abs().sum() / g["actual"].sum(),
                     "within_10pct": 100 * float((g["error"].abs() <= 0.1 * g["actual"]).mean()),
                     "coverage_5_95_pct": (100 * float(((cov["actual"] >= cov["lower"])
                                                        & (cov["actual"] <= cov["upper"])).mean())
                                           if len(cov) else np.nan),
                     "n_with_interval": len(cov)})
    return pd.DataFrame(rows)


def summarise_cows(cows: pd.DataFrame) -> pd.DataFrame:
    """Cow-level (cohort cow-day) WAPE by horizon, pooled sums."""
    if cows.empty:
        return pd.DataFrame()
    g = cows.groupby("horizon").agg(origins=("origin", "nunique"), cow_days=("cow_days", "sum"),
                                    abs_error_sum=("abs_error_sum", "sum"),
                                    error_sum=("error_sum", "sum"),
                                    squared_error_sum=("squared_error_sum", "sum"),
                                    actual_sum=("actual_sum", "sum"))
    out = pd.DataFrame({"origins": g["origins"], "cow_days": g["cow_days"],
                        "mae_per_cow_day": g["abs_error_sum"] / g["cow_days"],
                        "rmse_per_cow_day": np.sqrt(g["squared_error_sum"] / g["cow_days"]),
                        "bias_pct": 100 * g["error_sum"] / g["actual_sum"],
                        "wape_pct": 100 * g["abs_error_sum"] / g["actual_sum"]})
    out["accuracy_pct"] = 100 - out["wape_pct"]
    return out.reset_index()


def block_of(origin: str) -> str:
    """Notebook 6 chose the model with data through SELECTION_END: earlier origins carry
    that selection hindsight; later ones are out of sample for the selection too."""
    return "after_selection" if date.fromisoformat(origin) > SELECTION_END else "selection_period"
