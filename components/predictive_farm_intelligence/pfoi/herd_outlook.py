"""Two-year herd milk outlook with bounds and reliability markers (notebook 07, section 9).

Section 1-8 of notebook 07 forecast the next day / week / month. This module forecasts
every calendar month up to ``OUTLOOK_MONTHS`` (24) ahead from one origin (the 1st of a
month), in mean litres per day, with:

* **herd movement over the horizon.** The milking herd of each future month comes from
  a *milking path*: either the **herd engine** (``engine``: the structural projection
  of calvings, dry-offs, exits and lactation stage from the herd at the origin, run once
  per month start with only facts before it) or a **damped trend** (``trend``: the last
  28-day trend applied for at most ``TREND_DAYS`` days, then held). The base of a month
  is the recent litres per cow x the path's milking herd;
* **a direct multi-horizon network** (``torch_mlp_horizon``): one network for all
  horizons, with the horizon, the target month's season, the milking path (relative
  change, projected calvings, dry-offs and fresh-cow share), the same season one year
  earlier (calvings and the change in litres per cow) and every origin input of
  ``herd_torch``. It learns a bounded log correction to the base. ``_nomove`` drops the
  herd-movement inputs (ablation); ``torch_q_horizon`` is a 5/50/95% quantile network;
* **bounds:** the 5% and 95% quantiles of the chosen model's own past errors per
  horizon band (log actual / forecast), from walk-forward back-tests. Bands without
  enough errors are extrapolated from the last measured band (widening with the square
  root of the horizon) and labelled so; widths never shrink with the horizon;
* **markers:** the horizon where back-tested accuracy drops significantly (trailing
  3-horizon mean more than ``DROP_PP`` points below horizon 1), where fewer than
  ``RELIABLE_WITHIN10`` % of months are within +-10%, where skill over persistence is
  lost, and from where there are too few tested months to say anything.

Training windows are 30 days from every ``TRAIN_ORIGIN_STEP``-th day; a window is used
only if it ended by the training end. Herd-level aggregates only.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .cow_torch import CLIP, _fit_module, _modules, _Scaler, predict_net, resolve_device
from .herd_torch import (DEFAULT_PARAMS, FEATURE_FAMILIES, MAX_BASE_AGE_DAYS, MAX_DRIFT,
                         MOVEMENT_FAMILIES, STOP_EVERY_WEEKS, add_kalman, asof_features,
                         fit_local_level)

OUTLOOK_MONTHS = 24
TRAIN_WINDOW = 30
TRAIN_ORIGIN_STEP = 3
TREND_DAYS = 60
BOUND_Q = (0.05, 0.95)
OUTLOOK_QUANTILES = (0.05, 0.5, 0.95)
H_BANDS = ((1, 1), (2, 3), (4, 6), (7, 9), (10, 12), (13, 18), (19, 24))
MIN_ERRORS_PER_BAND = 5
MIN_PERIODS_PER_H = 3
DROP_PP = 5.0
RELIABLE_WITHIN10 = 85.0
FRESH_BINS = 6            # engine DIM bins of 10 days: bins 0-5 = 0-59 days in milk
PATH_FEATURES = ("path_ratio", "path_calvings", "path_dry_offs", "path_fresh", "path_engine",
                 "calv_ly", "pc_season_ly")
HORIZON_FEATURES = ("horizon", "doy_sin", "doy_cos", "period_days")
OUTLOOK_MODELS = ("persistence", "herd_structural", "torch_mlp_horizon",
                  "torch_mlp_horizon_nomove", "torch_q_horizon")


# ---------------------------------------------------------------- milking paths

@dataclass
class MilkingPaths:
    """``trend`` or ``engine``; engine runs are date-indexed frames per run date."""
    kind: str = "trend"
    runs: dict[pd.Timestamp, pd.DataFrame] = field(default_factory=dict)
    failed: list[date] = field(default_factory=list)


def month_starts(start, end) -> list[pd.Timestamp]:
    """1st of every month in [start, end]."""
    a = pd.Timestamp(start)
    first = a if a.day == 1 else (a + pd.offsets.MonthBegin(1))
    return list(pd.date_range(first, pd.Timestamp(end), freq="MS"))


def engine_paths(source, runs: list, horizon_days: int = OUTLOOK_MONTHS * 31 + 62,
                 cfg=None, verbose: bool = False) -> MilkingPaths:
    """Herd-engine projections from each run date (facts before it only): milking cows,
    calvings, dry-offs and the fresh-cow share (0-59 days in milk) per future day."""
    from .data import load_origin_inputs
    from .freeze import FROZEN_ENGINE
    from .herd_engine import project
    from .rates import estimate_rates

    cfg = cfg or FROZEN_ENGINE
    out = MilkingPaths("engine")
    t0 = time.perf_counter()
    for r in runs:
        r = pd.Timestamp(r)
        try:
            inputs = load_origin_inputs(source, r.date(), cfg)
        except ValueError:
            out.failed.append(r.date())
            continue
        rates = estimate_rates(inputs.rate_inputs, cfg)
        proj = project(inputs.state, rates, horizon_days, record_milk_mix=True)
        d = proj.daily
        mix = proj.milk_mix
        tot = mix.sum(axis=(1, 2, 3))
        fresh = mix[:, :, :FRESH_BINS, :].sum(axis=(1, 2, 3))
        col = lambda *names: sum(d[n].to_numpy(float) for n in names if n in d)  # noqa: E731
        frame = pd.DataFrame({"milking": d["milking"].to_numpy(float),
                              "calvings": d["calvings"].to_numpy(float),
                              "dry_offs": d["dry_offs"].to_numpy(float),
                              "fresh": np.where(tot > 0, fresh / np.where(tot > 0, tot, 1), np.nan),
                              "dry": col("dry_open", "dry_pregnant"),
                              "heifers": col("heifers_open", "heifers_pregnant"),
                              "calves": col("calves"), "total_herd": col("n_herd"),
                              "deaths": col("deaths"), "culls_sales": col("culls", "sales")},
                             index=pd.DatetimeIndex(pd.to_datetime(d["date"])))
        out.runs[r] = frame
        if verbose:
            print(f"  engine run {r.date()} ({time.perf_counter() - t0:,.0f}s)")
    return out


def synthetic_engine_paths(daily: pd.DataFrame, runs: list,
                           horizon_days: int = OUTLOOK_MONTHS * 31 + 62) -> MilkingPaths:
    """SYNTHETIC stand-in for the herd engine (synthetic runs only): from the year before
    each run, calvings by season, dry-off and exit rates per milking cow and the herd's
    other stocks per milking cow, projected day by day. Same columns as ``engine_paths``."""
    out = MilkingPaths("engine")
    calv_season = daily["calvings"].rolling(31, center=True, min_periods=1).mean()
    for r in runs:
        r = pd.Timestamp(r)
        hist = daily[daily.index < r].tail(365)
        if len(hist) < 365 or not hist["milking"].iloc[-1] > 0:
            out.failed.append(r.date())
            continue
        mk = hist["milking"].sum()
        dry_rate, exit_rate = hist["dry_offs"].sum() / mk, hist["culls"].sum() / mk
        ratio = {c: (hist[cols].sum(axis=1) / hist["milking"]).mean() for c, cols in
                 {"dry": ["dry_open", "dry_pregnant"], "heifers": ["heifers_open", "heifers_pregnant"],
                  "calves": ["calves"], "total_herd": ["n_herd"]}.items()}
        days = pd.date_range(r, periods=horizon_days)
        last_year = calv_season.reindex(days - pd.DateOffset(years=1)).fillna(hist["calvings"].mean())
        calv = last_year.to_numpy()
        m, rows = float(hist["milking"].iloc[-1]), []
        recent = list(hist["calvings"].to_numpy()[-60:])
        for t in range(horizon_days):
            dry, ex = dry_rate * m, exit_rate * m
            recent = (recent + [calv[t]])[-60:]
            rows.append((m, calv[t], dry, min(sum(recent) / m, 1.0), ex))
            m = max(m + calv[t] - dry - ex, 1.0)
        f = pd.DataFrame(rows, columns=["milking", "calvings", "dry_offs", "fresh", "culls_sales"],
                         index=days)
        for c, v in ratio.items():
            f[c] = v * f["milking"]
        f["deaths"] = hist["deaths"].mean()
        f["culls_sales"] += hist["sales"].mean()
        out.runs[r] = f
    return out


def engine_path_summary(paths: MilkingPaths) -> pd.DataFrame:
    """Per run: milking herd at the start, after 12 and after 24 months (aggregate)."""
    rows = []
    for r, f in paths.runs.items():
        m = f["milking"].to_numpy()
        rows.append({"run": r.date(), "milking_start": m[0],
                     "milking_12m": m[min(365, len(m) - 1)], "milking_24m": m[min(730, len(m) - 1)],
                     "calvings_24m": f["calvings"].iloc[:731].sum()})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- samples

@dataclass
class HorizonTable:
    meta: pd.DataFrame
    X: pd.DataFrame


def _pad(a: np.ndarray, n: int) -> np.ndarray:
    return np.concatenate([a, np.full(n, np.nan)]) if n > 0 else a


def _window_sums(arr: np.ndarray, a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Sum of finite values and their count over [a, b] (positions, inclusive)."""
    cs = np.concatenate([[0.0], np.cumsum(np.nan_to_num(arr))])
    cn = np.concatenate([[0], np.cumsum(np.isfinite(arr))])
    a = np.clip(a, 0, len(arr))
    b1 = np.clip(b + 1, 0, len(arr))
    return cs[b1] - cs[a], cn[b1] - cn[a]


def horizon_table(daily: pd.DataFrame, asof: pd.DataFrame, paths: MilkingPaths, mode: str,
                  origins: list | None = None, max_h: int = OUTLOOK_MONTHS) -> HorizonTable:
    """One row per origin x horizon. ``mode="train"``: 30-day windows from every
    ``TRAIN_ORIGIN_STEP``-th day; ``"score"``: calendar months from month-start
    ``origins`` (an origin may be the day after the data ends). Inputs use days before
    the origin only; ``actual`` is NaN where the month has no recorded day."""
    idx = daily.index
    n = len(idx)
    if mode == "train":
        s = np.arange(MAX_BASE_AGE_DAYS, n, TRAIN_ORIGIN_STEP)
    else:
        pos = (pd.DatetimeIndex(origins) - idx[0]).days.to_numpy()
        s = pos[(pos >= 1) & (pos <= n)]
    reps = np.repeat(s, max_h)
    h = np.tile(np.arange(1, max_h + 1), len(s))
    o_dates = idx[0] + pd.to_timedelta(reps, unit="D")
    if mode == "train":
        a = reps + TRAIN_WINDOW * (h - 1)
        lengths = np.full(len(a), TRAIN_WINDOW)
    else:
        starts = pd.DatetimeIndex([d + pd.DateOffset(months=int(k) - 1) for d, k in zip(o_dates, h)])
        a = reps + (starts - o_dates).days.to_numpy()
        lengths = starts.days_in_month.to_numpy()
    b = a + lengths - 1
    extra = int(max(b.max() + 1 - n, 0)) if len(b) else 0
    lit = _pad(daily["litres"].to_numpy(float), extra)
    pc = _pad(daily["per_cow"].to_numpy(float), extra)
    calv = daily["calvings"].to_numpy(float)
    sum_l, n_ok = _window_sums(lit, a, b)
    actual = np.where(n_ok > 0, sum_l / np.maximum(n_ok, 1), np.nan)
    X = asof.iloc[reps - 1].reset_index(drop=True)
    m0 = X["milking"].to_numpy(float)
    period_start = idx[0] + pd.to_timedelta(a, unit="D")
    mid = period_start + pd.to_timedelta((lengths - 1) / 2, unit="D")
    ang = 2 * np.pi * mid.dayofyear.to_numpy() / 365.25
    X["horizon"] = h
    X["doy_sin"], X["doy_cos"], X["period_days"] = np.sin(ang), np.cos(ang), lengths

    # Milking path: trend for every row, engine where a run covers it.
    t_mid = (a + b) / 2 - reps + 1
    drift = (X["milking_trend28"].fillna(0.0) / 28).to_numpy()
    ratio = np.exp(np.clip(drift * np.minimum(t_mid, TREND_DAYS), -MAX_DRIFT, MAX_DRIFT))
    p_calv = np.full(len(a), np.nan)
    p_dry = np.full(len(a), np.nan)
    p_fresh = np.full(len(a), np.nan)
    p_eng = np.zeros(len(a))
    if paths.kind == "engine" and paths.runs:
        run_dates = pd.DatetimeIndex(sorted(paths.runs))
        k = run_dates.searchsorted(o_dates, side="right") - 1
        for j, r in enumerate(run_dates):
            rows = np.flatnonzero(k == j)
            if not len(rows):
                continue
            f = paths.runs[r]
            off = (r - idx[0]).days
            i0, ia, ib = reps[rows] - off, a[rows] - off, b[rows] - off
            ok = (i0 >= 0) & (ib < len(f))
            rows, i0, ia, ib = rows[ok], i0[ok], ia[ok], ib[ok]
            mk = f["milking"].to_numpy()
            sm, cnt = _window_sums(mk, ia, ib)
            mean_m = sm / np.maximum(cnt, 1)
            with np.errstate(invalid="ignore", divide="ignore"):
                ratio[rows] = mean_m / mk[i0]
                p_calv[rows] = 100 * _window_sums(f["calvings"].to_numpy(), ia, ib)[0] / mean_m * TRAIN_WINDOW / (ib - ia + 1)
                p_dry[rows] = 100 * _window_sums(f["dry_offs"].to_numpy(), ia, ib)[0] / mean_m * TRAIN_WINDOW / (ib - ia + 1)
                fs, fn = _window_sums(f["fresh"].to_numpy(), ia, ib)
                p_fresh[rows] = fs / np.maximum(fn, 1)
            p_eng[rows] = 1.0
    X["path_ratio"], X["path_calvings"], X["path_dry_offs"] = ratio, p_calv, p_dry
    X["path_fresh"], X["path_engine"] = p_fresh, p_eng

    # Same season a year (else two years) earlier, only if it ended before the origin.
    calv_ly = np.full(len(a), np.nan)
    pc_ly = np.full(len(a), np.nan)
    pc_m28 = X["pc_m28"].fillna(X["pc_m7"]).to_numpy()
    for back in (730, 365):          # 365 overwrites 730 where both are available
        ok = b - back < reps
        aa, bb = a - back, b - back
        cs, _ = _window_sums(calv, aa, bb)
        with np.errstate(invalid="ignore", divide="ignore"):
            v = 100 * cs / m0 * TRAIN_WINDOW / lengths
        calv_ly = np.where(ok & (aa >= 0), v, calv_ly)
        ps, pn = _window_sums(pc, aa, bb)
        ref_s, ref_n = _window_sums(pc, reps - back - 28, reps - back - 1)
        with np.errstate(invalid="ignore", divide="ignore"):
            v = np.log((ps / pn) / (ref_s / ref_n))
        pc_ly = np.where(ok & (aa >= 0) & (pn > 0) & (ref_n > 0), v, pc_ly)
    X["calv_ly"], X["pc_season_ly"] = calv_ly, pc_ly

    fresh_base = X["days_since_ok"].to_numpy() <= MAX_BASE_AGE_DAYS
    base = np.where(fresh_base, pc_m28 * m0 * ratio, np.nan)
    pers = X["lit_m28"].fillna(X["lit_m7"]).to_numpy()
    meta = pd.DataFrame({"origin": o_dates, "horizon": h, "period_start": period_start,
                         "period_end": idx[0] + pd.to_timedelta(b, unit="D"),
                         "period_days": lengths, "actual": actual, "coverage": n_ok / lengths,
                         "milking_path": m0 * ratio, "base": base,
                         "persistence": np.where(fresh_base, pers, np.nan)})
    meta["has_base"] = np.isfinite(meta["base"]) & (meta["base"] > 0) & np.isfinite(meta["persistence"])
    X = X.drop(columns=["milking", "kal_level"], errors="ignore").replace([np.inf, -np.inf], np.nan)
    return HorizonTable(meta, X)


# ---------------------------------------------------------------- models

@dataclass
class OutlookModels:
    train_end: date
    meta: pd.DataFrame                       # scored rows (has_base) with predictions
    predictions: dict[str, np.ndarray]
    quantiles: np.ndarray | None             # (n, 3) of the quantile network, litres/day
    fitted: dict
    features: pd.DataFrame | None = None     # inputs of the scored rows (explanations)
    nets: dict = field(default_factory=dict)  # model -> (scaler, nets, columns, kind)


def fit_outlook(daily: pd.DataFrame, train_end: date, paths: MilkingPaths, origins: list,
                params: dict | None = None, device: str = "cpu", seed: int = 17,
                ensemble: int = 3, min_coverage: float = 1.0, max_h: int = OUTLOOK_MONTHS,
                use_ablation: bool = True, use_quantile: bool = True,
                verbose: bool = False) -> OutlookModels:
    """Fit on 30-day windows that ended by ``train_end``; forecast months 1..max_h from
    each month-start origin in ``origins``."""
    params = {**DEFAULT_PARAMS, **(params or {})}
    device = resolve_device(device)
    MLP, _ = _modules()
    t0 = time.perf_counter()
    asof = add_kalman(asof_features(daily), daily, fit_local_level(daily, train_end))
    tr = horizon_table(daily, asof, paths, "train", max_h=max_h)
    sc = horizon_table(daily, asof, paths, "score", origins=origins, max_h=max_h)
    m = tr.meta
    use = (m["has_base"] & (m["coverage"] >= min_coverage) & (m["actual"] > 0)
           & (m["period_end"] <= pd.Timestamp(train_end))).to_numpy()
    keep = sc.meta["has_base"].to_numpy()
    meta = sc.meta[keep].reset_index(drop=True)
    meta["scored"] = (meta["coverage"] >= min_coverage) & (meta["actual"] > 0)
    Xs = sc.X[keep].reset_index(drop=True)
    preds = {"persistence": meta["persistence"].to_numpy(float),
             "herd_structural": meta["base"].to_numpy(float)}
    fitted = {"train_windows": int(use.sum()), "paths": paths.kind, "params": params}
    out = OutlookModels(train_end, meta, preds, None, fitted, features=Xs)
    if use.sum() < 20 or not len(meta):
        if verbose:
            print(f"  outlook: only {int(use.sum())} training windows; networks skipped")
        return out
    Xt, mt = tr.X[use].reset_index(drop=True), m[use].reset_index(drop=True)
    base_t, act_t = mt["base"].to_numpy(), mt["actual"].to_numpy()
    y = np.clip(np.log(act_t / base_t), -CLIP, CLIP)
    weeks = ((mt["origin"] - mt["origin"].min()).dt.days // 7).to_numpy()
    stop = weeks % STOP_EVERY_WEEKS == STOP_EVERY_WEEKS - 1
    fit_idx, stop_idx = np.flatnonzero(~stop), np.flatnonzero(stop)
    base_s = meta["base"].to_numpy()
    cols = [c for c in Xt.columns if Xt[c].notna().any()]  # e.g. engine inputs on "trend"
    moving = set(PATH_FEATURES) - {"pc_season_ly"}
    for fam in MOVEMENT_FAMILIES:
        moving |= set(FEATURE_FAMILIES[fam])
    nomove = [c for c in cols if c not in moving]
    seeds = [seed + 101 * i for i in range(ensemble)]

    def family(name, use_cols):
        scaler = _Scaler.fit(Xt[use_cols])
        xt, xs = scaler.transform(Xt[use_cols]), scaler.transform(Xs[use_cols])
        outs, nets = [], []
        for s_ in seeds:
            net, info = _fit_module(MLP(xt.shape[1], tuple(params["hidden_large"]),
                                        params["dropout"]), [xt], y, fit_idx, stop_idx,
                                    params, device, s_, base_t, act_t)
            outs.append(predict_net(net, [xs], device))
            nets.append(net)
            fitted.setdefault("epochs", {})[name] = (info["best_epoch"], info["epochs"])
        preds[name] = base_s * np.exp(np.clip(np.mean(outs, axis=0), -CLIP, CLIP))
        out.nets[name] = (scaler, nets, list(use_cols), "mean")

    family("torch_mlp_horizon", cols)
    if use_ablation:
        family("torch_mlp_horizon_nomove", nomove)
    if use_quantile:
        scaler = _Scaler.fit(Xt[cols])
        xt, xs = scaler.transform(Xt[cols]), scaler.transform(Xs[cols])
        net, info = _fit_module(MLP(xt.shape[1], tuple(params["hidden_large"]), params["dropout"],
                                    n_out=len(OUTLOOK_QUANTILES)),
                                [xt], y, fit_idx, stop_idx, params, device, seed, base_t, act_t,
                                quantiles=OUTLOOK_QUANTILES)
        q = np.sort(np.clip(predict_net(net, [xs], device), -CLIP, CLIP), axis=1)
        out.quantiles = base_s[:, None] * np.exp(q)
        out.nets["torch_q_horizon"] = (scaler, [net], list(cols), "median")
        preds["torch_q_horizon"] = out.quantiles[:, 1]
        fitted.setdefault("epochs", {})["torch_q_horizon"] = (info["best_epoch"], info["epochs"])
    fitted["seconds"] = time.perf_counter() - t0
    if verbose:
        print(f"  outlook fit to {train_end}: {int(use.sum()):,} training windows, "
              f"{len(meta):,} origin-months ({fitted['seconds']:,.0f}s)")
    return out


def outlook_errors(models: OutlookModels, score_until: date, label: str) -> pd.DataFrame:
    """Long table of scored origin-months: one row per model."""
    meta = models.meta
    mask = (meta["scored"] & (meta["period_end"] <= pd.Timestamp(score_until))).to_numpy()
    rows = []
    for model, p in models.predictions.items():
        ok = mask & np.isfinite(p)
        rows.append(pd.DataFrame({
            "window": label, "model": model, "origin": meta["origin"][ok],
            "horizon": meta["horizon"][ok], "period_start": meta["period_start"][ok],
            "actual": meta["actual"][ok], "forecast": p[ok],
            "persistence": meta["persistence"][ok]}))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def horizon_backtest(daily: pd.DataFrame, cuts: list, score_until: date, paths: MilkingPaths,
                     fit_kwargs: dict, verbose: bool = False) -> pd.DataFrame:
    """Walk-forward: fit at each cut, forecast 1..24 months from every month start up to
    the next cut; score months that ended by ``score_until``."""
    errs = []
    for k, (t_end, nxt) in enumerate(zip(cuts[:-1], cuts[1:]), start=1):
        t_end, nxt = pd.Timestamp(t_end), pd.Timestamp(nxt)
        origins = month_starts(t_end + pd.Timedelta(days=1), nxt)
        if not origins:
            continue
        m = fit_outlook(daily, t_end.date(), paths, origins, verbose=verbose, **fit_kwargs)
        e = outlook_errors(m, score_until, f"window_{k}")
        if len(e):
            errs.append(e)
    return pd.concat(errs, ignore_index=True) if errs else pd.DataFrame()


# ---------------------------------------------------------------- read-outs

def horizon_accuracy(errors: pd.DataFrame, max_h: int = OUTLOOK_MONTHS) -> pd.DataFrame:
    """Accuracy by model and horizon on the origin-months every model forecast."""
    if errors.empty:
        return pd.DataFrame()
    key = ["window", "origin", "horizon"]
    common = errors.groupby(key)["model"].nunique()
    full = common[common == errors["model"].nunique()].index
    e = errors.set_index(key).loc[full].reset_index()
    rows = []
    for (model, h), g in e.groupby(["model", "horizon"]):
        act, f, p = g["actual"].to_numpy(), g["forecast"].to_numpy(), g["persistence"].to_numpy()
        mae, mae_p = np.mean(np.abs(f - act)), np.mean(np.abs(p - act))
        rows.append({"model": model, "horizon": int(h), "periods": len(g),
                     "accuracy_pct": 100 - 100 * np.abs(f - act).sum() / act.sum(),
                     "within_10pct": 100 * np.mean(np.abs(f - act) / act <= 0.10),
                     "bias_pct": 100 * (f - act).sum() / act.sum(),
                     "skill_vs_persistence_pct": 100 * (1 - mae / mae_p) if mae_p > 0 else np.nan})
    out = pd.DataFrame(rows)
    grid = pd.MultiIndex.from_product([out["model"].unique(), range(1, max_h + 1)],
                                      names=["model", "horizon"])
    out = out.set_index(["model", "horizon"]).reindex(grid).reset_index()
    out["periods"] = out["periods"].fillna(0).astype(int)
    return out


def pooled_outlook_accuracy(errors: pd.DataFrame) -> pd.DataFrame:
    """One score per model over all horizons (errors weighted by litres)."""
    e = errors.assign(abs_err=(errors["forecast"] - errors["actual"]).abs())
    g = e.groupby("model").agg(origin_months=("actual", "size"), actual=("actual", "sum"),
                               abs_err=("abs_err", "sum"))
    g["accuracy_pct"] = 100 - 100 * g["abs_err"] / g["actual"]
    return g.drop(columns=["actual", "abs_err"]).sort_values("accuracy_pct", ascending=False).reset_index()


ML_PREFIX = "torch_"   # machine-learning (PyTorch) candidates


def choose_models(pooled: pd.DataFrame, exclude: tuple[str, ...] = ("persistence",),
                  score: str = "accuracy_pct") -> dict:
    """The best candidate and the best machine-learning candidate (``torch_*``) by
    ``score``; ``models`` lists them once each (one entry when the best is a network)."""
    p = pooled[~pooled["model"].isin(exclude)].sort_values(score, ascending=False)
    best = p["model"].iloc[0] if len(p) else None
    ml = p[p["model"].str.startswith(ML_PREFIX)]
    best_ml = ml["model"].iloc[0] if len(ml) else None
    return {"best": best, "best_ml": best_ml,
            "models": list(dict.fromkeys(m for m in (best, best_ml) if m))}


def horizon_markers(acc: pd.DataFrame, model: str, drop_pp: float = DROP_PP,
                    reliable: float = RELIABLE_WITHIN10, min_periods: int = MIN_PERIODS_PER_H,
                    max_h: int = OUTLOOK_MONTHS) -> pd.DataFrame:
    """Horizons (months ahead) where the forecast stops being dependable."""
    a = acc[acc["model"] == model].set_index("horizon").reindex(range(1, max_h + 1))
    tested = a["periods"].fillna(0) >= min_periods
    rows = []
    untested = [h for h in a.index if not tested[h]]
    first_untested = next((h for h in untested if all(not tested[k] for k in range(h, max_h + 1))),
                          None)
    t = a[tested]
    if len(t):
        ref = t["accuracy_pct"].iloc[0]
        trail = t["accuracy_pct"].rolling(3, min_periods=1).mean()
        drop = trail[trail < ref - drop_pp]
        if len(drop):
            rows.append(("significant_drop", int(drop.index[0]),
                         f"trailing 3-horizon accuracy more than {drop_pp:g} points below "
                         f"horizon {int(t.index[0])} ({ref:.1f}%)"))
        low = t[t["within_10pct"] < reliable]
        if len(low):
            rows.append(("below_85pct_rule", int(low.index[0]),
                         f"fewer than {reliable:g}% of months within +-10%"))
        noskill = t[t["skill_vs_persistence_pct"] <= 0]
        if len(noskill):
            rows.append(("no_skill_vs_persistence", int(noskill.index[0]),
                         "not better than holding the last 28-day level"))
    if first_untested is not None:
        rows.append(("untested_from", int(first_untested),
                     f"fewer than {min_periods} back-tested months at every later horizon"))
    return pd.DataFrame(rows, columns=["marker", "horizon", "meaning"])


def error_bands(errors: pd.DataFrame, model: str, q: tuple[float, float] = BOUND_Q,
                max_h: int = OUTLOOK_MONTHS) -> pd.DataFrame:
    """Per horizon: lower / upper multipliers from quantiles of log(actual / forecast)
    pooled within horizon bands; extrapolated where a band has too few errors."""
    e = errors[(errors["model"] == model) & (errors["forecast"] > 0)]
    rel = np.log(e["actual"] / e["forecast"])
    rows, last = [], None
    for lo_h, hi_h in H_BANDS:
        r = rel[(e["horizon"] >= lo_h) & (e["horizon"] <= hi_h)]
        mid = (lo_h + hi_h) / 2
        if len(r) >= MIN_ERRORS_PER_BAND:
            # Bounds always contain the forecast itself.
            lo, hi = min(np.quantile(r, q[0]), 0.0), max(np.quantile(r, q[1]), 0.0)
            status = "measured"
            last = (lo, hi, mid)
        elif last is not None:
            # Keep the last measured centre; widen the half-width with sqrt(horizon).
            w = np.sqrt(mid / last[2])
            c, half = (last[0] + last[1]) / 2, (last[1] - last[0]) / 2
            lo, hi, status = min(c - half * w, 0.0), max(c + half * w, 0.0), "extrapolated"
        else:
            lo, hi, status = np.nan, np.nan, "none"
        for h in range(lo_h, min(hi_h, max_h) + 1):
            rows.append({"horizon": h, "band": f"{lo_h}-{hi_h}", "errors": len(r),
                         "lower_log": lo, "upper_log": hi, "status": status})
    out = pd.DataFrame(rows)
    # Never narrower than at a shorter horizon.
    out["lower_log"] = np.minimum.accumulate(out["lower_log"].fillna(np.inf).to_numpy())
    out["upper_log"] = np.maximum.accumulate(out["upper_log"].fillna(-np.inf).to_numpy())
    out.loc[~np.isfinite(out["lower_log"]), "lower_log"] = np.nan
    out.loc[~np.isfinite(out["upper_log"]), "upper_log"] = np.nan
    out["lower_pct"] = 100 * (np.exp(out["lower_log"]) - 1)
    out["upper_pct"] = 100 * (np.exp(out["upper_log"]) - 1)
    return out


def band_coverage(errors: pd.DataFrame, model: str, bands: pd.DataFrame) -> pd.DataFrame:
    """Share of scored months inside the bounds, by horizon band (target: 90%)."""
    e = errors[errors["model"] == model].merge(bands[["horizon", "band", "lower_log", "upper_log"]],
                                               on="horizon")
    rel = np.log(e["actual"] / e["forecast"])
    e["inside"] = (rel >= e["lower_log"]) & (rel <= e["upper_log"])
    return (e.groupby("band", sort=False).agg(months=("inside", "size"),
                                               inside_pct=("inside", "mean"))
            .assign(inside_pct=lambda d: 100 * d["inside_pct"]).reset_index())


def build_outlook(models: OutlookModels, model: str, bands: pd.DataFrame,
                  markers: pd.DataFrame) -> pd.DataFrame:
    """The 24 forecast months from the last origin, with bounds and reliability."""
    meta = models.meta
    origin = meta["origin"].max()
    rows = meta["origin"] == origin
    f = meta.loc[rows, ["origin", "horizon", "period_start", "period_end", "period_days",
                        "milking_path", "base"]].copy()
    f["forecast"] = models.predictions[model][rows.to_numpy()]
    f = f.merge(bands[["horizon", "lower_log", "upper_log", "status"]], on="horizon", how="left")
    f["lower"] = f["forecast"] * np.exp(f["lower_log"])
    f["upper"] = f["forecast"] * np.exp(f["upper_log"])
    if models.quantiles is not None:
        q = models.quantiles[rows.to_numpy()]
        f["q05_network"], f["q95_network"] = q[:, 0], q[:, 2]
    f["forecast_month_total"] = f["forecast"] * f["period_days"]
    first = {r.marker: r.horizon for r in markers.itertuples()}
    cut = min([v for k, v in first.items()] or [np.inf])
    f["reliability"] = np.where(f["horizon"] < cut, "tested", "beyond a marker")
    if "untested_from" in first:
        f.loc[f["horizon"] >= first["untested_from"], "reliability"] = "untested"
    f = f.rename(columns={"status": "bound_status"})
    return f.drop(columns=["lower_log", "upper_log"])


# ---------------------------------------------------------------- charts (aggregate)

MARKER_STYLE = {"significant_drop": ("#dc2626", "--"), "below_85pct_rule": ("#f59e0b", "--"),
                "no_skill_vs_persistence": ("#7c3aed", ":"), "untested_from": ("#6b7280", "-.")}


def plot_horizon_accuracy(acc: pd.DataFrame, models: list[str], markers: pd.DataFrame, path,
                          title: str):
    import matplotlib.pyplot as plt

    fig, (a1, a2, a3) = plt.subplots(3, 1, figsize=(13, 10), sharex=True,
                                     gridspec_kw={"height_ratios": [3, 3, 1.4]})
    for m in models:
        g = acc[acc["model"] == m].sort_values("horizon")
        style = dict(lw=2.2) if m == models[0] else dict(lw=1, alpha=0.8)
        a1.plot(g["horizon"], g["accuracy_pct"], marker="o", ms=3, label=m, **style)
        a2.plot(g["horizon"], g["within_10pct"], marker="o", ms=3, label=m, **style)
    g = acc[acc["model"] == models[0]].sort_values("horizon")
    a3.bar(g["horizon"], g["periods"], color="#9ca3af")
    a2.axhline(RELIABLE_WITHIN10, color="#f59e0b", lw=0.8)
    for ax in (a1, a2, a3):
        for r in markers.itertuples():
            c, ls = MARKER_STYLE.get(r.marker, ("black", "--"))
            ax.axvline(r.horizon - 0.5, color=c, ls=ls, lw=1.4,
                       label=f"{r.marker} (month {r.horizon})" if ax is a1 else None)
        ax.grid(alpha=0.3)
    a1.set_ylabel("accuracy %")
    a2.set_ylabel("months within +-10 %")
    a3.set_ylabel("tested months")
    a3.set_xlabel("months ahead")
    a1.legend(fontsize=7, ncol=2)
    a1.set_title(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    return fig


def plot_outlook(daily: pd.DataFrame, outlook: pd.DataFrame, markers: pd.DataFrame, path,
                 model: str, history_months: int = 36):
    import matplotlib.pyplot as plt

    hist = daily["litres"].resample("MS").mean()
    hist = hist[hist.index >= outlook["period_start"].min() - pd.DateOffset(months=history_months)]
    fig, ax = plt.subplots(figsize=(14, 5.5))
    ax.plot(hist.index, hist.to_numpy(), "o-", ms=3, color="black", lw=1,
            label="recorded (mean litres/day)")
    x = outlook["period_start"]
    ax.fill_between(x, outlook["lower"], outlook["upper"], color="#1f77b4", alpha=0.18,
                    label=f"{round(100 * (BOUND_Q[1] - BOUND_Q[0]))}% bounds (past errors)")
    ax.plot(x, outlook["forecast"], "o-", ms=3, color="#1f77b4", label=f"forecast ({model})")
    ext = outlook["bound_status"] == "extrapolated"
    if ext.any():
        ax.fill_between(x[ext], outlook["lower"][ext], outlook["upper"][ext], facecolor="none",
                        edgecolor="#1f77b4", hatch="//", lw=0, label="bounds extrapolated")
    for r in markers.itertuples():
        c, ls = MARKER_STYLE.get(r.marker, ("black", "--"))
        at = outlook.loc[outlook["horizon"] == r.horizon, "period_start"]
        if len(at):
            ax.axvline(at.iloc[0], color=c, ls=ls, lw=1.4, label=f"{r.marker}: month {r.horizon}")
    ax.set_title("Two-year herd milk outlook, mean litres per day per month", fontsize=10)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7, ncol=2, loc="upper left")
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    return fig


def _gapped(x, y, max_days: int = 70):
    """Insert a NaN where consecutive points are far apart, so lines never bridge a gap."""
    x = pd.Series(pd.to_datetime(x)).reset_index(drop=True)
    y = np.asarray(y, dtype=float)
    order = np.argsort(x.to_numpy())
    x, y = x.iloc[order].reset_index(drop=True), y[order]
    jumps = np.flatnonzero(x.diff().dt.days.to_numpy()[1:] > max_days) + 1
    if not len(jumps):
        return x, y
    return (pd.Series(np.insert(x.to_numpy(), jumps, x.to_numpy()[jumps - 1] + np.timedelta64(1, "D"))),
            np.insert(y, jumps, np.nan))


def plot_outlook_fit(daily: pd.DataFrame, fit: OutlookModels, model: str, pre_errors: pd.DataFrame,
                     test_errors: pd.DataFrame, path, title: str, train_end, valid_end,
                     gap=None, bands: pd.DataFrame | None = None,
                     horizons: tuple[int, ...] = (1, 3, 6, 12)):
    """Fitted vs recorded herd milk per months-ahead horizon (litres/day per month).

    * grey dashed: the final fit (trained to ``valid_end``) on months it was trained on,
      i.e. in-sample, not a test;
    * orange: walk-forward forecasts on pre-test data (each from a model trained only on
      earlier blocks, out-of-sample; the validation span is shaded yellow);
    * blue: test forecasts (trained to ``valid_end``), with the 5-95% bounds from
      pre-test errors when ``bands`` is given;
    * grey line: persistence on the same test months."""
    import matplotlib.pyplot as plt

    te, ve = pd.Timestamp(train_end), pd.Timestamp(valid_end)
    rec = daily.resample("MS").agg({"litres": "mean", "ok": "mean"})
    rec = rec[rec["ok"] > 0]["litres"]
    hs = [h for h in horizons if (fit.meta["horizon"] == h).any()]
    fig, axes = plt.subplots(len(hs), 1, figsize=(15, 3.3 * len(hs)), sharex=True, squeeze=False)
    b = bands.set_index("horizon") if bands is not None else None
    for ax, h in zip(axes[:, 0], hs):
        ax.axvspan(rec.index.min(), te, color="#f3f4f6", alpha=0.9, label="training")
        ax.axvspan(te, ve, color="#fde68a", alpha=0.4, label="validation")
        ax.axvspan(ve, rec.index.max(), color="#bfdbfe", alpha=0.25, label="test")
        if gap is not None:
            ax.axvspan(pd.Timestamp(gap[0]), pd.Timestamp(gap[1]), color="#d1d5db", alpha=0.8,
                       label="recording gap (excluded)")
        ax.plot(rec.index, rec.to_numpy(), "o", ms=3, color="black", label="recorded (monthly mean)")
        m = fit.meta
        # in-sample months with a record only (nothing to compare inside the gap)
        ins = ((m["horizon"] == h) & (m["period_end"] <= ve) & (m["actual"] > 0)).to_numpy()
        if model in fit.predictions:
            ax.plot(*_gapped(m["period_start"][ins], fit.predictions[model][ins]), ls="--", lw=1,
                    color="#94a3b8", label="training fit (in-sample, not a test)")
        pe = pre_errors[(pre_errors["model"] == model) & (pre_errors["horizon"] == h)]
        if len(pe):
            ax.plot(*_gapped(pe["period_start"], pe["forecast"]), "o-", ms=3, lw=1, color="#f59e0b",
                    label="walk-forward out-of-sample (pre-test)")
        tt = test_errors[(test_errors["model"] == model) & (test_errors["horizon"] == h)].sort_values("period_start")
        if len(tt):
            x = pd.to_datetime(tt["period_start"])
            ax.plot(x, tt["persistence"], lw=0.9, color="#6b7280", label="persistence (test)")
            ax.plot(x, tt["forecast"], "o-", ms=4, lw=1.4, color="#1f77b4", label=f"{model}: test forecast")
            if b is not None and h in b.index and np.isfinite(b.loc[h, "lower_log"]):
                ax.fill_between(x, tt["forecast"] * np.exp(b.loc[h, "lower_log"]),
                                tt["forecast"] * np.exp(b.loc[h, "upper_log"]), color="#1f77b4",
                                alpha=0.15, label="5-95% bounds (pre-test errors)")
        ax.set_title(f"{h} month{'s' if h > 1 else ''} ahead: herd milk, litres per day", fontsize=10)
        ax.grid(alpha=0.3)
        if ax is axes[0, 0]:
            ax.legend(fontsize=7, ncol=5, loc="upper left")
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    return fig


def next_origin(daily: pd.DataFrame) -> pd.Timestamp:
    """First month start after the last day of data."""
    last = daily.index.max()
    return last + pd.Timedelta(days=1) if (last + pd.Timedelta(days=1)).day == 1 \
        else last + pd.offsets.MonthBegin(1)


def outlook_end(origin, months: int = OUTLOOK_MONTHS) -> date:
    return (pd.Timestamp(origin) + pd.DateOffset(months=months) - timedelta(days=1)).date()
