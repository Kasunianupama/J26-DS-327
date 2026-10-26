"""Frontend outputs of the combined herd milk model (notebook 09).

Turns the herd milk models (``herd_torch`` one-step, ``herd_outlook`` 24 months),
notebook 06's per-cow input (``herd_cow_link``) and the herd-movement path (herd engine)
into what the PFOI page reads (``frontend/src/data/pfoi/contract.ts``) and the
``c1_output`` contract (``shared/schemas/pfoi_outlook.py``). Files only: nothing here
writes to a database.

* **record status and withheld forecasts:** freshness, completeness, plausibility and
  source agreement of the milk records; milk is withheld (not silently dropped) when no
  trusted day exists in the last 28 days;
* **one consistent path:** the 24-month outlook is the master. The live one-step daily
  and weekly forecasts are laid over its first weeks (their ratio to the monthly level
  decays with a 7-day half-life); months 2+ are rescaled to the monthly forecast. Daily,
  weekly and monthly values are sums of the same daily path, in litres per period;
* **bounds:** 5% / 95% empirical bounds per grain and horizon. Monthly from the
  outlook's back-test errors per horizon band; daily and weekly combine the one-step
  error of that grain with the monthly band of the month (in quadrature, log scale);
* **quality flag and reliability:** ``high`` before the first reliability marker,
  ``moderate`` beyond a marker, ``limited`` for untested horizons or stale records;
* **explanations (additive, exact):** forecast month h minus the recent recorded level
  = herd size (projected milking cows) + yield level (recent litres per cow) + the
  network correction split by exact Shapley values over input groups mapped to the
  page's factors (herd_size, stage_mix, parity_mix, pregnancy_mix, yield_level, thi,
  mastitis, cow_model_correction, residual). Rows give month-to-month changes, so the
  parts of a period add up to the change from the previous period. Past months:
  exact split of each recorded change into herd size and litres per cow;
* **evidence:** back-test rows in litres per period (MAE, RMSE, bias, coverage, n) for
  the model, persistence and seasonal naive; the evidence ladder on identical periods;
  status badges (``not interpretable`` when n < 12); replay rows of past forecasts;
* **herd series:** milking, dry, heifers, calves, total herd, calvings, dry-offs,
  deaths, culls and sales from the same path, with bounds from the path's own
  back-test against recorded herd counts;
* **reproducibility:** configuration hash, seeds, cut dates, training ends and the
  saved network weights.
Herd-level aggregates only.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .cow_torch import CLIP, predict_net
from .herd_torch import PER_COW_LIMIT, STOCKS

COMBINED_MODEL_NAME = "pfoi-herd-milk-combined-1.11.0-dev"
PAGE_GRAIN = {"daily": "day", "weekly": "week", "monthly": "month"}
PAGE_SERIES = {"herd_milk": "milk_litres", "milking": "milking", "dry": "dry",
               "heifers": "heifers", "calves": "calves", "total_herd": "total_herd",
               "calvings": "calvings", "dry_offs": "dry_offs", "deaths": "deaths",
               "culls_sales": "culls_sales"}
C1_SERIES = {"herd_milk": "herd_milk", "total_herd": "n_herd", "milking": "milking",
             "calvings": "calvings", "dry_offs": "dry_offs"}   # shared OutlookSeries
STOCK_SERIES = ("milking", "dry", "heifers", "calves", "total_herd")
EVENT_SERIES = ("calvings", "dry_offs", "deaths", "culls_sales")
DAILY_H, WEEKLY_H = 365, 52      # a year ahead at every grain (months go to 24)
MIN_DISPLAY_COVERAGE = 0.5      # partly recorded weeks/months shown (as estimates) from this share
OVERLAY_HALF_LIFE = 7.0
LOOKBACK_DAYS, FRESH_LIMIT_DAYS = 28, 7
MIN_INTERPRETABLE_N = 12
Q = (0.05, 0.95)
# Network input groups -> page factors (contract MilkFactor).
FACTOR_GROUPS = {
    "herd_size": ("path_ratio", "path_engine", "log_milking", "herd_per_milking",
                  "milking_trend28", "net_milking_in_28", "drift_to_mid", "exits_7", "exits_28",
                  "entries_7", "entries_28"),
    "stage_mix": ("dim_0-60", "dim_61-150", "dim_151-305", "dim_305+", "path_fresh",
                  "calvings_7", "calvings_28", "births_7", "births_28", "dry_offs_7",
                  "dry_offs_28", "path_calvings", "path_dry_offs", "calv_ly"),
    "parity_mix": ("parity_1", "parity_2", "parity_3+"),
    "pregnancy_mix": ("dry_preg_per_milking", "dry_open_per_milking", "heifer_preg_per_milking"),
    "thi": ("thi_m7", "thi_max_m7", "rain_m7"),
    "mastitis": ("mastitis_28", "udder_28", "blood_alarms_7", "cond_alarms_7"),
    "cow_model_correction": ("cow06_gap",),
}   # every other input (milk history, season, horizon) -> yield_level


# ---------------------------------------------------------------- record status

def record_status(daily: pd.DataFrame, as_of=None, lookback: int = LOOKBACK_DAYS,
                  fresh_limit: int = FRESH_LIMIT_DAYS) -> dict:
    """F1: are the milk records current, stale, or too old to forecast milk?"""
    as_of = pd.Timestamp(as_of) if as_of is not None else daily.index.max()
    upto = daily[daily.index <= as_of]
    trusted = upto.index[upto["ok"].to_numpy()]
    last = trusted.max() if len(trusted) else None
    stale = int((as_of - last).days) if last is not None else None
    window = upto[upto.index > as_of - pd.Timedelta(days=lookback)]
    fresh = int(window["ok"].sum())
    pc = window.loc[window["ok"], "per_cow"]
    plaus = float(((pc > 0) & (pc <= PER_COW_LIMIT)).mean()) if len(pc) else None
    withheld = fresh == 0
    checks = [
        {"check": "freshness", "ok": stale is not None and stale <= fresh_limit, "value": stale,
         "detail": f"last trusted milk day {last.date() if last is not None else 'none'}; "
                   f"limit {fresh_limit} days"},
        {"check": "completeness", "ok": fresh / lookback >= 0.5, "value": round(fresh / lookback, 3),
         "detail": f"{fresh} of the last {lookback} days have trusted milk records"},
        {"check": "plausibility", "ok": None if plaus is None else plaus == 1.0, "value": plaus,
         "detail": "share of recorded days with 0 < litres per milking cow <= 18"},
        {"check": "source_agreement", "ok": None, "value": None,
         "detail": "one source (identified cows only); nothing to compare"},
    ]
    status = "withheld" if withheld else ("stale" if stale > fresh_limit else "current")
    reason = None
    if withheld:
        reason = "no_trusted_milk_days"
    elif status == "stale":
        reason = "milk_records_old"
    text = {None: None,
            "no_trusted_milk_days": f"No trusted milk days in the last {lookback} days, so the "
                                    "milk forecast is withheld; herd counts are still shown.",
            "milk_records_old": f"Milk records are {stale} days old, so ranges are less certain."}
    return {"status": status, "last_trusted_day": None if last is None else str(last.date()),
            "staleness_days": stale, "fresh_days": fresh, "lookback_days": lookback,
            "checks": checks, "milk_withheld": withheld, "reason": reason,
            "reason_text": text[reason],
            "rule": f"withheld when no trusted milk day in the last {lookback} days; "
                    f"stale when the last one is more than {fresh_limit} days old"}


def carry_last_herd_state(daily: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """When the herd tables end before the frame does, carry the last recorded herd state
    (stocks, lactation-stage and parity mix) to the frame's end, so a live forecast can
    start the day after it. Milk, events and drivers stay missing. Returns the frame and
    the number of days carried (0 when nothing was missing)."""
    last = daily["milking"].dropna().index.max()
    carried = int((daily.index.max() - last).days) if pd.notna(last) else 0
    if carried <= 0:
        return daily, 0
    out = daily.copy()
    cols = [c for c in out.columns if c in STOCKS or c.startswith(("dim_", "parity_"))]
    out.loc[out.index > last, cols] = np.nan
    out[cols] = out[cols].ffill()
    return out, carried


def pad_future(daily: pd.DataFrame, days: int = 45) -> pd.DataFrame:
    """Calendar days after the data with no records, so live one-step forecasts can be
    made from origins after the last data day."""
    extra = pd.date_range(daily.index.max() + pd.Timedelta(days=1), periods=days, name=daily.index.name)
    pad = pd.DataFrame(np.nan, index=extra, columns=daily.columns)
    pad["ok"] = False
    num = daily.drop(columns="ok").astype(float)
    out = pd.concat([num.assign(ok=daily["ok"]), pad])
    out["ok"] = out["ok"].astype(bool)
    for c in out.columns:
        if c != "ok":
            out[c] = pd.to_numeric(out[c], errors="coerce")
    # The herd itself is assumed unchanged after the last data day (stocks and mix carried
    # forward); events, milk and drivers stay missing.
    carry = [c for c in out.columns if c in STOCKS or c.startswith(("dim_", "parity_"))]
    out[carry] = out[carry].ffill()
    return out


# ---------------------------------------------------------------- bounds

def log_bounds(actual, forecast, q=Q) -> tuple[float, float, int]:
    """Quantiles of log(actual / forecast), always containing 0 (the forecast)."""
    a, f = np.asarray(actual, float), np.asarray(forecast, float)
    ok = (a > 0) & (f > 0)
    if ok.sum() < 5:
        return np.nan, np.nan, int(ok.sum())
    r = np.log(a[ok] / f[ok])
    return min(np.quantile(r, q[0]), 0.0), max(np.quantile(r, q[1]), 0.0), int(ok.sum())


def onestep_bands(models, model_by_grain: dict, blocks=("validation", "test")) -> dict:
    """grain -> (lower_log, upper_log, n) of one-step errors on the given blocks."""
    out = {}
    for grain, model in model_by_grain.items():
        meta = models.tables.get(grain)
        if meta is None or model not in models.predictions or grain not in models.predictions[model]:
            continue
        m = meta["block"].isin(blocks).to_numpy() & meta["scored"].to_numpy()
        out[grain] = log_bounds(meta["actual"].to_numpy()[m], models.predictions[model][grain][m])
    return out


def _quad(a: float, b: float, sign: int) -> float:
    a = 0.0 if not np.isfinite(a) else a
    b = 0.0 if not np.isfinite(b) else b
    return sign * math.sqrt(a * a + b * b)


# ---------------------------------------------------------------- consistent path

def reconcile_path(origin, monthly: pd.DataFrame, short: pd.DataFrame,
                   half_life: float = OVERLAY_HALF_LIFE) -> pd.DataFrame:
    """Daily path (litres/day) over the outlook months.

    ``monthly``: period_start, forecast (litres/day), one row per month from ``origin``.
    ``short``: grain, period_start, period_end, forecast (litres/day) of the live one-step
    daily / weekly forecasts. Their ratio to the monthly level holds over their own days
    and decays afterwards; months 2+ are rescaled to the monthly forecast exactly."""
    origin = pd.Timestamp(origin)
    m = monthly.sort_values("period_start").reset_index(drop=True)
    end = m["period_start"].iloc[-1] + pd.offsets.MonthEnd(0)
    days = pd.date_range(origin, end)
    month_of = days.to_period("M").to_timestamp()
    level = pd.Series(m.set_index("period_start")["forecast"]).reindex(month_of).to_numpy()
    ratio = np.ones(len(days))
    last_ratio, last_t = 1.0, -1
    for grain in ("weekly", "daily"):            # daily overrides weekly on its own day
        s = short[short["grain"] == grain]
        for r in s.itertuples():
            a, b = (pd.Timestamp(r.period_start) - origin).days, (pd.Timestamp(r.period_end) - origin).days
            if b < 0 or a >= len(days):
                continue
            a, b = max(a, 0), min(b, len(days) - 1)
            rr = r.forecast / np.nanmean(level[a:b + 1])
            ratio[a:b + 1] = rr
            if b > last_t:
                last_ratio, last_t = rr, b
    t = np.arange(len(days))
    after = t > last_t
    ratio[after] = 1 + (last_ratio - 1) * 0.5 ** ((t[after] - last_t) / half_life)
    path = pd.DataFrame({"date": days, "month": month_of, "litres": level * ratio})
    first = month_of[0]
    for mon, g in path[path["month"] != first].groupby("month"):
        target = m.set_index("period_start").loc[mon, "forecast"]
        path.loc[g.index, "litres"] *= target / g["litres"].mean()
    return path


def path_periods(path: pd.DataFrame, origin) -> dict[str, pd.DataFrame]:
    """Daily (h 1-14), Monday weeks (h 1-13) and months (h 1-24) as litres per period."""
    origin = pd.Timestamp(origin)
    p = path.set_index("date")["litres"]
    daily = p.iloc[:DAILY_H].reset_index().rename(columns={"date": "period_start", "litres": "mean"})
    daily["period_end"], daily["days"] = daily["period_start"], 1
    first_monday = origin + pd.Timedelta(days=(7 - origin.weekday()) % 7)
    weeks = []
    for h in range(WEEKLY_H):
        a = first_monday + pd.Timedelta(days=7 * h)
        w = p[a:a + pd.Timedelta(days=6)]
        if len(w) == 7:
            weeks.append({"period_start": a, "period_end": a + pd.Timedelta(days=6), "mean": w.mean(), "days": 7})
    months = (p.groupby(p.index.to_period("M")).agg(["mean", "size"]).reset_index())
    months = pd.DataFrame({"period_start": months["date"].dt.to_timestamp(), "mean": months["mean"],
                           "days": months["size"]})
    months["period_end"] = months["period_start"] + pd.offsets.MonthEnd(0)
    out = {"daily": daily, "weekly": pd.DataFrame(weeks), "monthly": months}
    for g, f in out.items():
        f["horizon"] = np.arange(1, len(f) + 1)
        f["month_horizon"] = ((f["period_start"].dt.year - origin.year) * 12
                              + f["period_start"].dt.month - origin.month + 1)
        f["forecast"] = f["mean"] * f["days"]
    return out


def quality_flag(month_h: int, markers: pd.DataFrame, rec: dict) -> str:
    first = {r.marker: r.horizon for r in markers.itertuples()}
    if rec["status"] != "current" or month_h >= first.get("untested_from", 10 ** 6):
        return "limited"
    if month_h >= min(first.values(), default=10 ** 6):
        return "moderate"
    return "high"


def reliability_status(month_h: int, markers: pd.DataFrame) -> str:
    first = {r.marker: r.horizon for r in markers.itertuples()}
    if month_h >= first.get("untested_from", 10 ** 6):
        return "cannot be validated with current data"
    return "development"


def milk_rows(periods: dict, origin, month_bands: pd.DataFrame, step_bands: dict,
              markers: pd.DataFrame, rec: dict, model_version: str,
              core_version: str | None) -> pd.DataFrame:
    """Milk OutlookRows (backend vocabulary) for every grain from one path."""
    mb = month_bands.set_index("horizon")
    rows = []
    for grain, f in periods.items():
        for r in f.itertuples():
            h_m = int(min(max(r.month_horizon, 1), mb.index.max()))
            lo_m, hi_m = mb.loc[h_m, "lower_log"], mb.loc[h_m, "upper_log"]
            if grain == "monthly":
                lo, hi = lo_m, hi_m
            else:
                lo_s, hi_s, _ = step_bands.get(grain, (np.nan, np.nan, 0))
                lo, hi = _quad(lo_s, lo_m, -1), _quad(hi_s, hi_m, 1)
            rows.append({"origin_date": pd.Timestamp(origin).date(), "target_period": r.period_start.date(),
                         "grain": grain, "horizon": int(r.horizon), "series": "herd_milk",
                         "forecast": float(r.forecast),
                         "lower": float(r.forecast * math.exp(lo)) if np.isfinite(lo) else None,
                         "upper": float(r.forecast * math.exp(hi)) if np.isfinite(hi) else None,
                         "quality_flag": quality_flag(h_m, markers, rec),
                         "status": reliability_status(h_m, markers), "month_horizon": h_m,
                         "model_version": model_version, "core_version": core_version})
    return pd.DataFrame(rows)


def withheld_rows(origin, months: int = 24) -> list[dict]:
    o = pd.Timestamp(origin)
    end = (o + pd.DateOffset(months=months) - pd.Timedelta(days=1)).date()
    return [{"series": "milk_litres", "grain": PAGE_GRAIN[g], "from": str(o.date()), "to": str(end),
             "reason": "no trusted milk days in the last 28 days"} for g in PAGE_GRAIN]


# ---------------------------------------------------------------- herd series

def _period_value(frame: pd.DataFrame, series: str, a, b) -> float:
    part = frame.loc[a:b, series] if series in frame else pd.Series(dtype=float)
    if not len(part):
        return np.nan
    return float(part.mean() if series in STOCK_SERIES else part.sum())


def _actual_herd(daily: pd.DataFrame) -> pd.DataFrame:
    d = pd.DataFrame(index=daily.index)
    d["milking"] = daily["milking"]
    d["dry"] = daily["dry_open"] + daily["dry_pregnant"]
    d["heifers"] = daily["heifers_open"] + daily["heifers_pregnant"]
    d["calves"], d["total_herd"] = daily["calves"], daily["n_herd"]
    d["calvings"], d["dry_offs"], d["deaths"] = daily["calvings"], daily["dry_offs"], daily["deaths"]
    d["culls_sales"] = daily["culls"] + daily["sales"]
    return d


def actual_rows(daily: pd.DataFrame, months: int | None = None) -> pd.DataFrame:
    """ActualRows for the page (page vocabulary): recorded milk per day, Monday week and
    month in litres for the period. A week or month is scoreable only when every day is
    recorded; when at least ``MIN_DISPLAY_COVERAGE`` of its days are, it gets an estimate
    (mean of the recorded days x days, ``scoreable`` false, shown but never scored); below
    that it is null. ``coverage`` = share of the period's days recorded. Also
    the recorded herd per month (stocks as means, events as sums). ``months=None`` (default)
    keeps the whole recorded history; a number keeps only the last ``months`` months."""
    d = daily
    if months is not None:
        start = (daily.index.max() - pd.DateOffset(months=months)).to_period("M").to_timestamp()
        d = daily[daily.index >= start]
    first = d.index[d["ok"].to_numpy() | d["milking"].notna().to_numpy()].min()
    d = d[d.index >= first.to_period("M").to_timestamp()] if pd.notna(first) else d
    rows = []
    for grain, rule in (("day", "D"), ("week", "W-MON"), ("month", "MS")):
        kw = {"label": "left", "closed": "left"} if grain == "week" else {}
        g = d.resample(rule, **kw).agg({"litres": "mean", "ok": ["mean", "size"]})
        g.columns = ["per_day", "share", "days"]
        expected = {"day": 1, "week": 7}.get(grain)
        for t, r in g.iterrows():
            n_exp = expected or t.days_in_month
            cover = float(r["share"]) * r["days"] / n_exp
            full = cover >= 1.0 - 1e-9
            show = (cover >= MIN_DISPLAY_COVERAGE if grain != "day" else full) and pd.notna(r["per_day"])
            rows.append({"period": str(t.date()), "grain": grain, "series": "milk_litres",
                         "value": float(r["per_day"] * n_exp) if show else None,
                         "source": "delpro" if show else None, "scoreable": bool(full and show),
                         "coverage": round(cover, 3)})
    herd = _actual_herd(d)
    m = pd.concat([herd[list(STOCK_SERIES)].resample("MS").mean(),
                   herd[list(EVENT_SERIES)].resample("MS").sum()], axis=1)
    for t, r in m.iterrows():
        for s in m.columns:
            rows.append({"period": str(t.date()), "grain": "month", "series": PAGE_SERIES.get(s, s),
                         "value": None if pd.isna(r[s]) else float(r[s]), "source": None, "scoreable": True})
    return pd.DataFrame(rows)


def herd_path_errors(daily: pd.DataFrame, paths, max_h: int = 24) -> pd.DataFrame:
    """The herd path from every run vs recorded herd counts, month by month."""
    actual = _actual_herd(daily)
    end = daily.index.max()
    rows = []
    for r, f in paths.runs.items():
        for h in range(1, max_h + 1):
            a = r + pd.DateOffset(months=h - 1)
            b = a + pd.offsets.MonthEnd(0)
            if b > end or b > f.index.max():
                break
            for s in (*STOCK_SERIES, *EVENT_SERIES):
                rows.append({"run": r, "horizon": h, "period_start": a, "series": s,
                             "actual": _period_value(actual, s, a, b),
                             "forecast": _period_value(f, s, a, b)})
    return pd.DataFrame(rows)


def herd_bands(errors: pd.DataFrame, max_h: int = 24) -> pd.DataFrame:
    """Per series and horizon band: 5/95% quantiles of log((actual+1)/(forecast+1)),
    widening only; horizons with too few errors reuse the last measured band."""
    from .herd_outlook import H_BANDS
    rows = []
    for s, g in errors.groupby("series"):
        last = (np.nan, np.nan)
        for lo_h, hi_h in H_BANDS:
            e = g[(g["horizon"] >= lo_h) & (g["horizon"] <= hi_h)].dropna()
            lo, hi, n = log_bounds(e["actual"] + 1, e["forecast"] + 1)
            if not np.isfinite(lo):
                lo, hi = last
            last = (lo, hi)
            for h in range(lo_h, min(hi_h, max_h) + 1):
                rows.append({"series": s, "horizon": h, "lower_log": lo, "upper_log": hi, "errors": n})
    out = pd.DataFrame(rows)
    out["lower_log"] = out.groupby("series")["lower_log"].transform(lambda x: x.cummin())
    out["upper_log"] = out.groupby("series")["upper_log"].transform(lambda x: x.cummax())
    return out


def herd_rows(paths, origin, bands: pd.DataFrame, rec: dict, markers: pd.DataFrame,
              model_version: str, core_version: str | None, max_h: int = 24) -> pd.DataFrame:
    """Monthly herd OutlookRows from the path run at ``origin`` (herd counts are shown
    even when milk is withheld)."""
    o = pd.Timestamp(origin)
    earlier = [r for r in paths.runs if r <= o]
    if not earlier:
        return pd.DataFrame()
    run = max(earlier)            # the run at the origin, else the latest one before it
    f = paths.runs[run]
    b = bands.set_index(["series", "horizon"])
    rows = []
    for h in range(1, max_h + 1):
        a = o + pd.DateOffset(months=h - 1)
        e = a + pd.offsets.MonthEnd(0)
        for s in (*STOCK_SERIES, *EVENT_SERIES):
            v = _period_value(f, s, a, e)
            lo, hi = (b.loc[(s, h), "lower_log"], b.loc[(s, h), "upper_log"]) if (s, h) in b.index else (np.nan, np.nan)
            rows.append({"origin_date": o.date(), "target_period": a.date(), "grain": "monthly",
                         "horizon": h, "series": s, "forecast": v,
                         "lower": (v + 1) * math.exp(lo) - 1 if np.isfinite(lo) else None,
                         "upper": (v + 1) * math.exp(hi) - 1 if np.isfinite(hi) else None,
                         "quality_flag": "high" if h <= 12 else "moderate",
                         "status": "development", "month_horizon": h, "path_run": run.date(),
                         "model_version": model_version, "core_version": core_version})
    out = pd.DataFrame(rows)
    out["lower"] = out["lower"].clip(lower=0)
    return out


# ---------------------------------------------------------------- explanations

def _factor_of(col: str) -> str:
    for factor, cols in FACTOR_GROUPS.items():
        if col in cols:
            return factor
    return "yield_level"


def _net_output(entry, x_raw: pd.DataFrame, device: str) -> np.ndarray:
    scaler, nets, cols, kind = entry
    z = scaler.transform(x_raw[cols])
    outs = []
    for n in nets:
        o = predict_net(n, [z], device)
        outs.append(np.sort(o, axis=1)[:, 1] if o.ndim == 2 else o)
    return np.clip(np.mean(outs, axis=0), -CLIP, CLIP)


def shapley_groups(entry, x: pd.DataFrame, device: str = "cpu") -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """Exact Shapley values of the network's log correction over factor groups, with the
    training medians as reference. Returns (phi per row x group, output, reference output)."""
    scaler, _, cols, _ = entry
    ref = pd.Series(scaler.medians, index=scaler.columns)
    groups = sorted({_factor_of(c) for c in cols})
    members = {g: [c for c in cols if _factor_of(c) == g] for g in groups}
    k, n = len(groups), len(x)
    value = {}
    for size in range(k + 1):
        for subset in itertools.combinations(range(k), size):
            xs = x[cols].copy()
            for j, g in enumerate(groups):
                if j not in subset:
                    xs[members[g]] = ref[members[g]].to_numpy()
            value[subset] = _net_output(entry, xs, device)
    phi = np.zeros((n, k))
    for j in range(k):
        for size in range(k):
            w = math.factorial(size) * math.factorial(k - size - 1) / math.factorial(k)
            for subset in itertools.combinations([i for i in range(k) if i != j], size):
                with_j = tuple(sorted(subset + (j,)))
                phi[:, j] += w * (value[with_j] - value[subset])
    return pd.DataFrame(phi, columns=groups), value[tuple(range(k))], value[()]


def outlook_attribution(models, model: str, origin, recent_level: float, published: pd.DataFrame,
                        device: str = "cpu") -> pd.DataFrame:
    """Exact parts of every published month (litres/day), as changes from the previous
    month (month 1: from the recent recorded level). ``published``: period_start, mean
    (litres/day) of the reconciled path; the difference to the model's own monthly value
    (the short-term overlay in month 1) is reported as residual."""
    meta = models.meta
    rows = (meta["origin"] == pd.Timestamp(origin)).to_numpy()
    m = meta[rows].reset_index(drop=True)
    X = models.features[rows].reset_index(drop=True)
    F = models.predictions[model][rows]
    base = m["base"].to_numpy()
    m0 = np.exp(X["log_milking"].to_numpy())
    pc = base / m["milking_path"].to_numpy()
    parts = pd.DataFrame(0.0, index=range(len(m)), columns=[
        "herd_size", "stage_mix", "parity_mix", "pregnancy_mix", "yield_level", "thi",
        "mastitis", "cow_model_correction", "residual"])
    parts["herd_size"] += pc * (m["milking_path"].to_numpy() - m0)
    parts["yield_level"] += pc * m0 - recent_level
    net_part = F - base
    if model in models.nets:
        phi, out, ref_out = shapley_groups(models.nets[model], X, device)
        ref_part = base * (np.exp(ref_out) - 1)
        parts["residual"] += ref_part
        total = phi.sum(axis=1).to_numpy()
        share = np.divide(phi.to_numpy(), total[:, None], out=np.zeros_like(phi.to_numpy()),
                          where=np.abs(total[:, None]) > 1e-12)
        rest = net_part - ref_part
        for j, g in enumerate(phi.columns):
            parts[g] += share[:, j] * rest
        parts["residual"] += np.where(np.abs(total) > 1e-12, 0.0, rest)
    else:
        parts["residual"] += net_part
    pub = published.set_index("period_start")["mean"].reindex(m["period_start"]).to_numpy()
    parts["residual"] += np.nan_to_num(pub - F)
    # ``parts`` of month h add up to (published_h - recent level); rows are changes from
    # the previous month (month 1: from the recent level), so they add up period by period.
    change = parts.diff()
    if len(change):
        change.iloc[0] = parts.iloc[0]
    out = change.assign(target_period=m["period_start"].dt.date.to_numpy(),
                        horizon=m["horizon"].to_numpy())
    long = out.melt(id_vars=["target_period", "horizon"], var_name="factor", value_name="contribution")
    long["kind"] = "forecast"
    return long


def past_attribution(daily: pd.DataFrame, months: int = 12, min_coverage: float = 0.8) -> pd.DataFrame:
    """Recorded month-to-month changes split exactly into herd size and litres per cow
    (midpoint rule): dL = dM x mean(pc) + dpc x mean(M)."""
    mth = daily.resample("MS").agg({"litres": "mean", "milking": "mean", "ok": "mean"})
    mth = mth[mth["ok"] >= min_coverage].dropna(subset=["litres"])
    mth["pc"] = mth["litres"] / mth["milking"]
    rows = []
    prev = None
    for t, r in mth.iterrows():
        if prev is not None and (t - prev[0]).days <= 31:
            p = prev[1]
            rows += [{"target_period": t.date(), "factor": "herd_size",
                      "contribution": (r["milking"] - p["milking"]) * (r["pc"] + p["pc"]) / 2},
                     {"target_period": t.date(), "factor": "yield_level",
                      "contribution": (r["pc"] - p["pc"]) * (r["milking"] + p["milking"]) / 2}]
        prev = (t, r)
    out = pd.DataFrame(rows)
    if len(out):
        keep = sorted(out["target_period"].unique())[-months:]
        out = out[out["target_period"].isin(keep)]
        out["kind"] = "past"
    return out


# ---------------------------------------------------------------- evidence

def seasonal_naive(daily: pd.DataFrame, period_start, days: int, origin) -> float:
    """Same calendar period one year earlier (mean litres/day), if fully recorded at
    80% and ended before the origin."""
    a = pd.Timestamp(period_start) - pd.DateOffset(years=1)
    b = a + pd.Timedelta(days=int(days) - 1)
    if b >= pd.Timestamp(origin):
        return np.nan
    part = daily.loc[a:b]
    if len(part) == 0 or part["ok"].mean() < 0.8:
        return np.nan
    return float(part["litres"].mean())


def _score(e: pd.DataFrame) -> dict:
    err = (e["forecast"] - e["actual"]) * e["days"]
    return {"mae": float(err.abs().mean()), "rmse": float(np.sqrt((err ** 2).mean())),
            "bias": float(err.mean()), "n_origins": int(e["origin"].nunique()), "n": len(e)}


def backtest_rows(errors: pd.DataFrame, daily: pd.DataFrame, model: str, bands: pd.DataFrame | None,
                  block: str, grain: str = "monthly") -> pd.DataFrame:
    """BacktestRows (litres per period) for the model, persistence and seasonal naive on
    the same origin-periods. ``errors``: origin, horizon, period_start, actual, forecast,
    persistence (litres/day) for ``model``."""
    e = errors[errors["model"] == model].copy()
    if e.empty:
        return pd.DataFrame()
    e["days"] = [pd.Timestamp(p).days_in_month if grain == "monthly" else (7 if grain == "weekly" else 1)
                 for p in e["period_start"]]
    e["seasonal"] = [seasonal_naive(daily, p, d, o) for p, d, o in
                     zip(e["period_start"], e["days"], e["origin"])]
    b = bands.set_index("horizon") if bands is not None else None
    rows = []
    for h, g in e.groupby("horizon"):
        cov = None
        if b is not None and h in b.index and np.isfinite(b.loc[h, "lower_log"]):
            r = np.log(g["actual"] / g["forecast"])
            cov = float(((r >= b.loc[h, "lower_log"]) & (r <= b.loc[h, "upper_log"])).mean())
        rows.append({"block": block, "model": "pfoi", "grain": grain, "horizon": int(h),
                     "series": "herd_milk", **_score(g), "coverage": cov})
        rows.append({"block": block, "model": "persistence", "grain": grain, "horizon": int(h),
                     "series": "herd_milk", **_score(g.assign(forecast=g["persistence"])),
                     "coverage": None})
        s = g.dropna(subset=["seasonal"])
        if len(s):
            rows.append({"block": block, "model": "seasonal_naive", "grain": grain, "horizon": int(h),
                         "series": "herd_milk", **_score(s.assign(forecast=s["seasonal"])),
                         "coverage": None})
    return pd.DataFrame(rows)


def onestep_errors(models, model: str, blocks: tuple[str, ...]) -> pd.DataFrame:
    """One-step scored periods of ``model`` in the errors layout of ``herd_outlook``."""
    out = []
    for grain, meta in models.tables.items():
        if model not in models.predictions or grain not in models.predictions[model]:
            continue
        m = meta["block"].isin(blocks).to_numpy() & meta["scored"].to_numpy()
        p = models.predictions[model][grain]
        m &= np.isfinite(p)
        out.append(pd.DataFrame({"grain": grain, "model": model, "origin": meta["origin"][m],
                                 "horizon": 1, "period_start": meta["period_start"][m],
                                 "actual": meta["actual"][m], "forecast": p[m],
                                 "persistence": models.predictions["persistence"][grain][m]}))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


LADDER = (("persistence", "persistence"),
          ("structure: milking cows x litres per cow", "herd_structural"),
          ("+ learned correction, no herd movement", "torch_mlp_nomove"),
          ("+ herd movement and make-up", "torch_mlp_small"),
          ("+ notebook 06 per-cow yield", "torch_mlp_cow06"))


def evidence_ladder(models, block: str = "test", selected: dict | None = None) -> pd.DataFrame:
    """F7: each rung on the same one-step periods; ratio to persistence; n and status."""
    rows = []
    for grain, meta in models.tables.items():
        rungs = list(LADDER) + ([(f"selected ({selected[grain]})", selected[grain])]
                                if selected and grain in selected else [])
        rungs = [(l, m) for l, m in rungs if m in models.predictions and grain in models.predictions[m]]
        mask = (meta["block"] == block).to_numpy() & meta["scored"].to_numpy()
        for _, m in rungs:
            mask &= np.isfinite(models.predictions[m][grain])
        if not mask.any():
            continue
        a = meta["actual"].to_numpy()[mask]
        ref = np.mean(np.abs(models.predictions["persistence"][grain][mask] - a))
        for label, m in rungs:
            p = models.predictions[m][grain][mask]
            mae = float(np.mean(np.abs(p - a)))
            rows.append({"rung": label, "model": m, "grain": grain, "horizon": 1, "band": "all",
                         "n": int(mask.sum()), "mae": mae, "bias": float(np.mean(p - a)),
                         "wape": float(100 * np.abs(p - a).sum() / a.sum()),
                         "ratio_to_reference": mae / ref if ref > 0 else None,
                         "status": "not interpretable" if mask.sum() < MIN_INTERPRETABLE_N
                         else "development"})
    return pd.DataFrame(rows)


def replay_rows(errors: pd.DataFrame, model: str, bands: pd.DataFrame | None, grain: str,
                model_version: str, core_version: str | None) -> pd.DataFrame:
    """Past forecasts (test block) as OutlookRows, litres per period."""
    e = errors[errors["model"] == model]
    b = bands.set_index("horizon") if bands is not None else None
    rows = []
    for r in e.itertuples():
        days = pd.Timestamp(r.period_start).days_in_month if grain == "monthly" else (7 if grain == "weekly" else 1)
        f = r.forecast * days
        lo = hi = None
        if b is not None and r.horizon in b.index and np.isfinite(b.loc[r.horizon, "lower_log"]):
            lo, hi = f * math.exp(b.loc[r.horizon, "lower_log"]), f * math.exp(b.loc[r.horizon, "upper_log"])
        rows.append({"origin_date": pd.Timestamp(r.origin).date(), "target_period": pd.Timestamp(r.period_start).date(),
                     "grain": grain, "horizon": int(r.horizon), "series": "herd_milk", "forecast": f,
                     "lower": lo, "upper": hi, "quality_flag": "high", "actual": r.actual * days,
                     "model_version": model_version, "core_version": core_version})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- document

def config_hash(config: dict) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _page(rows: pd.DataFrame) -> list[dict]:
    if rows is None or rows.empty:
        return []
    r = rows.copy()
    r["grain"] = r["grain"].map(PAGE_GRAIN)
    r["series"] = r["series"].map(PAGE_SERIES).fillna(r["series"])
    for c in ("origin_date", "target_period"):
        if c in r:
            r[c] = r[c].astype(str)
    return json.loads(r.to_json(orient="records", date_format="iso"))


page_rows = _page   # public: rows in the page vocabulary


def c1_tables(outlook: pd.DataFrame, attribution: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Rows of the shared c1_output contract (backend vocabulary), validated by its
    Pydantic models; series outside the contract stay in the run document only."""
    from shared.schemas.pfoi_outlook import AttributionRow, OutlookRow

    cols = ["origin_date", "target_period", "grain", "horizon", "series", "forecast", "lower",
            "upper", "quality_flag", "model_version", "core_version"]
    acols = ["origin_date", "target_period", "grain", "series", "factor", "contribution", "kind",
             "model_version", "core_version"]
    if outlook is None or outlook.empty or "series" not in outlook:
        outlook = pd.DataFrame(columns=cols)
    if attribution is None or attribution.empty or "factor" not in attribution:
        attribution = pd.DataFrame(columns=acols)
    o = outlook[outlook["series"].isin(C1_SERIES)].copy()
    o["series"] = o["series"].map(C1_SERIES)
    o = o[cols]
    for rec in o.to_dict("records"):
        OutlookRow(**{k: (None if isinstance(v, float) and not np.isfinite(v) else v) for k, v in rec.items()})
    a = attribution.copy()[acols]
    for rec in a.to_dict("records"):
        AttributionRow(**rec)
    return o.reset_index(drop=True), a.reset_index(drop=True)


def run_document(**parts) -> dict:
    """The run-document keys this model fills (page vocabulary)."""
    doc = {
        "source": parts["source"], "model_version": parts["model_version"],
        "core_version": parts.get("core_version"), "origin_date": str(parts["origin"].date()),
        "data_through": str(parts["data_through"].date()),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "outlook": _page(parts["outlook"]), "attribution": _page(parts["attribution"]),
        "backtest": _page(parts["backtest"]), "replay": _page(parts["replay"]),
        "record_status": parts["record_status"], "withheld": parts["withheld"],
        "interval_method": parts["interval_method"],
        "evidence_ladder": json.loads(parts["ladder"].to_json(orient="records")),
        "horizon_reliability": json.loads(parts["markers"].to_json(orient="records")),
        "milk_model": parts["milk_model"], "cow06_input": parts["cow06_input"],
        "herd_path": parts["herd_path"], "reproducibility": parts["reproducibility"],
        # Best machine-learning model when it is not the published one (same outputs).
        "alternatives": parts.get("alternatives", []),
        "actuals": parts.get("actuals", []),
    }
    return doc


def realised_rows(daily: pd.DataFrame, origin) -> tuple[list[dict], str | None]:
    """Recorded outcomes on and after ``origin`` (the contract's ``realised``)."""
    o = pd.Timestamp(origin)
    after = daily[daily.index >= o]
    if after.empty:
        return [], None
    months = int((daily.index.max() - o).days // 28) + 2
    r = actual_rows(daily, months)
    r = r[pd.to_datetime(r["period"]) >= o]
    last = after.index[after["ok"].to_numpy()].max() if after["ok"].any() else None
    return json.loads(r.to_json(orient="records")), (None if last is None else str(last.date()))


def historic_document(daily: pd.DataFrame, fit, model: str, origin, paths, month_bands: pd.DataFrame,
                      step_bands: dict, markers: pd.DataFrame, herd_bands: pd.DataFrame,
                      step_models, step_winners: dict, model_version: str, core_version: str | None,
                      run_kind: str, common: dict, device: str = "cpu",
                      max_h: int = 24) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    """The page document of one past forecast date, as it was made then: the outlook
    from ``fit`` (a model trained only before ``origin``), one-step overlay from
    ``step_models`` when they hold that date, herd rows from the path run at ``origin``,
    history before ``origin`` and what was recorded afterwards (``realised``).
    ``common``: the keys shared with the live document (milk_model, interval_method, ...)."""
    o = pd.Timestamp(origin)
    before = daily[daily.index < o]
    rec = record_status(before)
    meta = fit.meta
    rows = (meta["origin"] == o).to_numpy()
    milk, withheld, attr = pd.DataFrame(), [], pd.DataFrame()
    if rec["milk_withheld"] or model not in fit.predictions or not rows.any():
        withheld = withheld_rows(o, max_h)
    else:
        short = []
        if step_models is not None:
            for g in ("daily", "weekly"):
                m, tab = step_winners.get(g), step_models.tables.get(g)
                if m and tab is not None and g in step_models.predictions.get(m, {}):
                    i = np.flatnonzero(tab["origin"] >= o)
                    if len(i) and (tab["origin"].iloc[i[0]] - o).days < 7:
                        k = i[0]
                        short.append({"grain": g, "period_start": tab["period_start"][k],
                                      "period_end": tab["period_end"][k],
                                      "forecast": step_models.predictions[m][g][k]})
        short = pd.DataFrame(short, columns=["grain", "period_start", "period_end", "forecast"])
        monthly = meta.loc[rows, ["period_start"]].assign(forecast=fit.predictions[model][rows])
        periods = path_periods(reconcile_path(o, monthly, short), o)
        milk = milk_rows(periods, o, month_bands, step_bands, markers, rec, model_version, core_version)
        recent = before.loc[before.index > o - pd.Timedelta(days=28), "litres"].mean()
        attr = outlook_attribution(fit, model, o, recent, periods["monthly"], device)
    herd = herd_rows(paths, o, herd_bands, rec, markers, model_version, core_version, max_h)
    if len(herd) and pd.Timestamp(herd["path_run"].iloc[0]) != o:
        herd = herd.iloc[0:0]          # past dates: only a herd path run exactly at the date
    past = past_attribution(before)
    attr = pd.concat([f for f in (attr, past) if len(f)], ignore_index=True)
    if len(attr):
        attr = attr.assign(origin_date=o.date(), grain="monthly", series="herd_milk",
                           model_version=model_version, core_version=core_version)
    outlook = pd.concat([f for f in (milk, herd) if len(f)], ignore_index=True)
    doc = run_document(source=common["source"], model_version=model_version, core_version=core_version,
                       origin=o, data_through=o - pd.Timedelta(days=1), outlook=outlook,
                       attribution=attr, backtest=pd.DataFrame(), replay=pd.DataFrame(),
                       record_status=rec, withheld=withheld,
                       interval_method=common.get("interval_method", {}),
                       ladder=common.get("ladder", pd.DataFrame()), markers=markers,
                       milk_model={**common.get("milk_model", {}), "run_kind": run_kind},
                       cow06_input=common.get("cow06_input", {}), herd_path=common.get("herd_path", {}),
                       reproducibility={**common.get("reproducibility", {}), "trained_through": str(fit.train_end)},
                       actuals=json.loads(actual_rows(before).to_json(orient="records")) if len(before) else [])
    doc["realised"], doc["realised_through"] = realised_rows(daily, o)
    doc["run_kind"] = run_kind
    return doc, outlook, attr


def save_model_state(path: Path, entries: dict) -> list[str]:
    """Network weights and scalers of the published models (CPU tensors)."""
    import torch

    state = {}
    for name, entry in entries.items():
        scaler, nets, cols = entry[0], entry[1], entry[2]
        state[name] = {"columns": list(cols), "scaler": {k: getattr(scaler, k).tolist()
                                                      for k in ("medians", "means", "stds", "indicator")},
                       "weights": [{k: v.detach().cpu() for k, v in n.state_dict().items()} for n in nets]}
    torch.save(state, path)
    return sorted(state)
