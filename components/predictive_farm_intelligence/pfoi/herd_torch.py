"""Herd milk with PyTorch and herd-movement inputs (notebook 07).

Notebook 06 forecasts each cow's yield. This module forecasts the **whole herd's milk**:
the clean target of ``docs/model_input2.md`` section 5 (milk per recorded cow x milking
herd, litres per day, placeholder and shipped milk never used), one value per day,
week (Monday start) or calendar month (mean litres per day over its recorded days).

Same protocol as notebook 06: recording gap excluded, 75 / 5 / 20 chronological split of
the recorded herd-days, walk-forward forecasts of the next period, tuning and pooled
selection on pre-test data only, untouched test.

**Herd movement as input.** Herd milk = milking cows x litres per cow, so every forecast
starts from a structural base

    base = per-cow level (last 7 recorded days) x projected milking cows,

where the milking count on the day before the origin is moved to the middle of the
target period along its last-28-day trend. The networks then learn a bounded log
correction to that base from (all known before the origin):

* milk history: last level, 7/28-day means, trend, record coverage, Kalman level;
* herd movement: calvings, dry-offs, exits, entries and births over 7 and 28 days per
  milking cow, net milking inflow, milking trend;
* herd composition: lactation-stage (DIM band) and parity shares, pregnant dry cows and
  heifers per milking cow (next calvings), total herd per milking cow;
* weather and health: lagged THI, rain, mastitis and sensor alarms per milking cow;
* calendar: season of the target period and its length.

Candidates per grain: ``persistence``, ``herd_structural`` (the base), ``herd_kalman``
(local-level Kalman per-cow yield x projected milking), ``torch_mlp_small``,
``torch_mlp_large`` (seed ensembles), ``torch_mlp_nomove`` (ablation: same network
without herd-movement and composition inputs), ``torch_gru`` (GRU over the last
``seq_len`` days of milk and movement), ``torch_q50`` (10/50/90% quantile network), each
also walk-forward recalibrated (``_recal``).

Weekly and monthly networks train on rolling windows (7 and 30 days from every day) so
they see many more samples than there are calendar periods; they are scored on calendar
weeks and months only. Herd level only: no animal key enters or leaves this module.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .cow_accuracy import DATA_SCOPES, TEST_END, TRAIN_START, chronological_split
from .cow_torch import (CLIP, QUANTILES, _fit_module, _modules, _Scaler,
                        assert_torch_safe_process, predict_net, resolve_device)

__all__ = ["assert_torch_safe_process", "chronological_split", "resolve_device"]

HERD_TORCH_MODEL_NAME = "pfoi-herd-milk-torch-1.9.0-dev"
HERD_TEST_NAMES = {"clean": "herd-milk-test-clean-75-5-20",
                   "through_mid2023": "herd-milk-test-through-mid2023-75-5-20"}
GRAINS = ("daily", "weekly", "monthly")
TRAIN_WINDOW_DAYS = {"daily": 1, "weekly": 7, "monthly": 30}
STOCKS = ("n_herd", "calves", "heifers_open", "heifers_pregnant", "milking", "dry_open",
          "dry_pregnant")
MOVES = ("calvings", "dry_offs", "exits", "entries", "births", "deaths", "culls", "sales")
DIM_SHARES = ("0-60", "61-150", "151-305", "305+")
PARITY_SHARES = ("1", "2", "3+")
DRIVERS = ("thi_mean", "thi_max", "rain_total_mm", "mastitis_episodes",
           "udder_teat_episodes", "n_blood_alarms", "n_conductivity_alarms")
FORBIDDEN_COLUMNS = ("milk_shipped", "milk_internal", "milk_hand_milked_est",
                     "milk_delpro_cows", "milk_delpro_unidentified", "milk_delpro_total",
                     "herd_milk_measured", "animal_key", "cow_id", "animal")
PER_COW_LIMIT = 18.0
MAX_BASE_AGE_DAYS = 28   # a base needs a recorded day in the 28 days before the origin
MAX_DRIFT = 0.2          # milking projection moves at most x0.82 .. x1.22
RECAL_LOOKBACK = {"daily": 28, "weekly": 8, "monthly": 3}   # scored periods
RECAL_MAX_AGE_DAYS = 120
RECAL_BOUNDS = (0.8, 1.25)
STOP_EVERY_WEEKS = 10
NETWORKS = ("torch_mlp_small", "torch_mlp_large")
DEFAULT_PARAMS = dict(dropout=0.3, lr=1e-3, weight_decay=1e-4, batch_size=64,
                      max_epochs=250, min_epochs=50, stop_drop_pp=0.5, stop_patience=15,
                      lr_patience=5, min_lr=1e-6, hidden_small=(64, 32),
                      hidden_large=(128, 64, 32))
MODEL_OPTIONS = dict(ensemble=3, use_kalman=True, use_gru=True, gru_seeds=1, seq_len=28,
                     gru_hidden=32, use_quantile=True, use_ablation=True, networks=NETWORKS)
SEARCH_SPACE = {"hidden_large": [(64, 32), (128, 64), (128, 64, 32), (256, 128, 64)],
                "dropout": [0.1, 0.2, 0.3, 0.4, 0.5], "lr": [3e-4, 1e-3, 3e-3],
                "weight_decay": [1e-5, 1e-4, 1e-3], "batch_size": [32, 64, 128]}


# ---------------------------------------------------------------- data (aggregates)

def load_herd_daily(source, start: date = TRAIN_START,
                    end: date = TEST_END + timedelta(days=1)) -> pd.DataFrame:
    """One row per calendar day: clean herd milk, herd stocks, movements, mix, drivers.

    ``source`` is a ``MilkSource`` (``SqlHerdSource`` on model_input2, or the synthetic
    test source). ``target_daily`` on model_input2 is already placeholder-free; litres
    are kept only on scoreable days. Herd-level aggregates only.
    """
    days = pd.date_range(start, end - timedelta(days=1), name="date")
    f = pd.DataFrame(index=days)
    t = source.target_daily(start, end).copy()
    t["date"] = pd.to_datetime(t["date"])
    t = t.drop_duplicates("date").set_index("date").reindex(days)
    litres = pd.to_numeric(t["target_litres"], errors="coerce")
    ok = t["is_scoreable"].astype("boolean").fillna(False).astype(bool) & litres.gt(0)
    p = source.panel_daily(start, end).copy()
    p["date"] = pd.to_datetime(p["date"])
    p = p.drop_duplicates("date").set_index("date").reindex(days)
    for c in (*STOCKS, *MOVES):
        f[c] = pd.to_numeric(p[c], errors="coerce") if c in p else np.nan
    mix = source.milking_mix_daily(start, end).copy()
    mix["date"] = pd.to_datetime(mix["date"])
    dim = mix.pivot_table(index="date", columns="dim_band", values="n", aggfunc="sum")
    par = mix.pivot_table(index="date", columns="parity_group", values="n", aggfunc="sum")
    known = dim.reindex(columns=list(DIM_SHARES)).fillna(0.0).reindex(days)
    tot = known.sum(axis=1).replace(0, np.nan)
    for b in DIM_SHARES:
        f[f"dim_{b}"] = known[b] / tot
    pk = par.reindex(columns=list(PARITY_SHARES)).fillna(0.0).reindex(days)
    ptot = pk.sum(axis=1).replace(0, np.nan)
    for q in PARITY_SHARES:
        f[f"parity_{q}"] = pk[q] / ptot
    drv = source.driver_daily(start, end).copy()
    drv["date"] = pd.to_datetime(drv["date"])
    drv = drv.drop_duplicates("date").set_index("date").reindex(days)
    for c in DRIVERS:
        f[c] = pd.to_numeric(drv[c], errors="coerce") if c in drv else np.nan
    f["ok"] = ok & f["milking"].gt(0)
    f["litres"] = litres.where(f["ok"])
    return finish_daily(f)


def finish_daily(f: pd.DataFrame) -> pd.DataFrame:
    f = f.copy()
    f["per_cow"] = (f["litres"] / f["milking"]).where(f["ok"])
    return f


def exclude_gap(daily: pd.DataFrame, gap: tuple[date, date] | None) -> pd.DataFrame:
    """Milk inside the recording gap is neither trained on nor scored. Herd movement is
    kept (it comes from presence intervals, recorded throughout)."""
    f = daily.copy()
    if gap is not None:
        inside = (f.index >= pd.Timestamp(gap[0])) & (f.index <= pd.Timestamp(gap[1]))
        f.loc[inside, "ok"] = False
        f.loc[inside, "litres"] = np.nan
    return finish_daily(f)


def synthetic_herd_daily(seed: int = 17, start: date = date(2016, 1, 1),
                         end: date = TEST_END + timedelta(days=1),
                         milk_from: date = date(2020, 8, 1)) -> pd.DataFrame:
    """SYNTHETIC fictional herd (not Farm X) with the columns of ``load_herd_daily``.

    Milking cows follow calvings, dry-offs and exits; litres per cow follow the
    lactation-stage mix, heat stress and noise, so herd movement carries real signal.
    """
    rng = np.random.default_rng(seed)
    days = pd.date_range(start, end - timedelta(days=1), name="date")
    n = len(days)
    doy = days.dayofyear.to_numpy()
    season = 1 + 0.35 * np.sin(2 * np.pi * (doy - 60) / 365.25)
    calv = rng.poisson(0.9 * season)
    milking = np.empty(n)
    dry = np.empty(n)
    exits_m = np.empty(n)
    m = 300.0
    for i in range(n):
        dry[i] = rng.poisson(0.85 * m / 300)
        exits_m[i] = rng.poisson(0.05 * m / 300)
        m = max(150.0, m + calv[i] - dry[i] - exits_m[i])
        milking[i] = m
    c = pd.Series(calv, index=days, dtype=float)
    s60, s150, s305 = (c.rolling(w, min_periods=1).sum().to_numpy() for w in (60, 150, 305))
    shares = np.stack([s60, s150 - s60, s305 - s150,
                       np.clip(milking - s305, 0.05 * milking, None)], axis=1)
    shares = shares / shares.sum(axis=1, keepdims=True)
    thi = 74 + 4 * np.sin(2 * np.pi * (doy - 100) / 365.25) + rng.normal(0, 1.2, n)
    drift = 1 + 0.08 * np.sin(2 * np.pi * np.arange(n) / 1500)
    per_cow = (8.5 * (1 + 0.35 * shares[:, 0] + 0.1 * shares[:, 1] - 0.4 * shares[:, 3])
               * (1 - 0.012 * np.clip(thi - 75, 0, None)) * drift
               * np.exp(rng.normal(0, 0.05, n)))
    f = pd.DataFrame(index=days)
    f["milking"] = milking
    f["dry_pregnant"] = 0.18 * milking * np.exp(rng.normal(0, 0.05, n))
    f["dry_open"] = 0.04 * milking
    f["heifers_pregnant"] = 0.15 * milking * season
    f["heifers_open"] = 0.2 * milking
    f["calves"] = 0.4 * milking
    f["n_herd"] = f[["milking", "dry_pregnant", "dry_open", "heifers_pregnant",
                     "heifers_open", "calves"]].sum(axis=1)
    f["calvings"], f["dry_offs"] = c.to_numpy(), dry
    f["deaths"] = rng.poisson(0.03, n)
    f["culls"], f["sales"] = exits_m, rng.poisson(0.05, n)
    f["exits"] = f["deaths"] + f["culls"] + f["sales"]
    f["entries"] = rng.poisson(0.02, n)
    f["births"] = c.to_numpy()
    for b, k in zip(DIM_SHARES, range(4)):
        f[f"dim_{b}"] = shares[:, k]
    f["parity_1"], f["parity_2"], f["parity_3+"] = 0.35, 0.3, 0.35
    f["thi_mean"], f["thi_max"] = thi, thi + 6
    f["rain_total_mm"] = rng.gamma(0.5, 6, n)
    f["mastitis_episodes"] = rng.poisson(0.2, n)
    f["udder_teat_episodes"] = rng.poisson(0.1, n)
    late = days >= pd.Timestamp(2025, 11, 1)
    f["n_blood_alarms"] = np.where(late, rng.poisson(30, n), 0)
    f["n_conductivity_alarms"] = np.where(late, rng.poisson(20, n), 0)
    ok = (days >= pd.Timestamp(milk_from)) & (rng.random(n) > 0.01)
    f["ok"] = ok
    f["litres"] = np.where(ok, per_cow * milking, np.nan)
    return finish_daily(f)


def herd_contract_checks(daily: pd.DataFrame, start: date = TRAIN_START,
                         end: date = TEST_END) -> pd.DataFrame:
    """Executable checks on the loaded herd frame (aggregate evidence only)."""
    ok = daily["ok"]
    pc = daily.loc[ok, "per_cow"]
    rows = [
        ("one row per calendar day", daily.index.is_unique and daily.index.is_monotonic_increasing
         and len(daily) == (daily.index.max() - daily.index.min()).days + 1,
         f"{len(daily):,} days"),
        ("dates inside the experiment", daily.index.min() >= pd.Timestamp(start)
         and daily.index.max() <= pd.Timestamp(end), f"{daily.index.min().date()} .. "
         f"{daily.index.max().date()}"),
        ("litres only on recorded days", daily.loc[~ok, "litres"].isna().all(),
         f"{int(ok.sum()):,} recorded days"),
        ("litres per milking cow in (0, 18] L", bool(len(pc)) and pc.gt(0).all()
         and pc.le(PER_COW_LIMIT).all(),
         f"min {pc.min():.2f} / max {pc.max():.2f} L per cow" if len(pc) else "none"),
        ("milking cows > 0 on recorded days", daily.loc[ok, "milking"].gt(0).all(),
         f"min {daily.loc[ok, 'milking'].min():,.0f}" if ok.any() else "none"),
        ("no keys, placeholder, shipped or DelPro-total milk columns",
         not set(FORBIDDEN_COLUMNS) & set(daily.columns), "column names only"),
    ]
    out = pd.DataFrame(rows, columns=["check", "passed", "aggregate_evidence"])
    out["status"] = np.where(out["passed"], "PASS", "FAIL")
    return out


def herd_year_summary(daily: pd.DataFrame) -> pd.DataFrame:
    """Per year: recorded days, milk level, milking herd and movement totals."""
    g = daily.groupby(daily.index.year)
    out = pd.DataFrame({
        "recorded_days": g["ok"].sum().astype(int),
        "mean_litres_per_day": g["litres"].mean(),
        "mean_litres_per_cow": g["per_cow"].mean(),
        "mean_milking_cows": g["milking"].mean(),
        "mean_herd": g["n_herd"].mean(),
        **{c: g[c].sum() for c in ("calvings", "dry_offs", "exits", "entries", "births")},
        "mean_thi": g["thi_mean"].mean(),
    })
    out.index.name = "year"
    return out.reset_index()


# ---------------------------------------------------------------- features

FEATURE_FAMILIES = {
    "milk history": ("lit_last", "days_since_ok", "lit_m7", "lit_m28", "pc_m7", "pc_m28",
                     "ok_share28", "lit_trend", "kal_gap", "kal_sd"),
    "herd movement": ("milking_trend28", "net_milking_in_28", "drift_to_mid",
                      *(f"{c}_{w}" for c in ("calvings", "dry_offs", "exits", "entries",
                                             "births") for w in (7, 28))),
    "herd composition": ("log_milking", *(f"dim_{b}" for b in DIM_SHARES),
                         *(f"parity_{q}" for q in PARITY_SHARES), "dry_preg_per_milking",
                         "dry_open_per_milking", "heifer_preg_per_milking",
                         "herd_per_milking"),
    "weather and health": ("thi_m7", "thi_max_m7", "rain_m7", "mastitis_28",
                           "udder_28", "blood_alarms_7", "cond_alarms_7"),
    "calendar": ("doy_sin", "doy_cos", "period_days"),
}
MOVEMENT_FAMILIES = ("herd movement", "herd composition")


def feature_catalogue() -> pd.DataFrame:
    return pd.DataFrame([(fam, c) for fam, cols in FEATURE_FAMILIES.items() for c in cols],
                        columns=["family", "feature"])


def asof_features(f: pd.DataFrame) -> pd.DataFrame:
    """Features through the end of each day (a forecast at origin o reads row o - 1)."""
    a = pd.DataFrame(index=f.index)
    lit, pc, m = f["litres"], f["per_cow"], f["milking"].where(f["milking"] > 0)
    a["lit_last"] = lit.ffill()
    last = pd.Series(np.where(f["ok"], np.arange(len(f)), np.nan), index=f.index).ffill()
    a["days_since_ok"] = np.arange(len(f)) - last
    a["lit_m7"] = lit.rolling(7, min_periods=1).mean()
    a["lit_m28"] = lit.rolling(28, min_periods=3).mean()
    a["pc_m7"] = pc.rolling(7, min_periods=1).mean()
    a["pc_m28"] = pc.rolling(28, min_periods=3).mean()
    a["ok_share28"] = f["ok"].astype(float).rolling(28, min_periods=1).mean()
    a["lit_trend"] = np.log(a["lit_m7"] / a["lit_m28"])
    a["milking"] = m
    a["log_milking"] = np.log(m)
    a["milking_trend28"] = np.log(m / m.shift(28))
    for c in ("calvings", "dry_offs", "exits", "entries", "births"):
        for w in (7, 28):
            a[f"{c}_{w}"] = 100 * f[c].rolling(w, min_periods=1).sum() / m
    a["net_milking_in_28"] = a["calvings_28"] - a["dry_offs_28"]
    for b in DIM_SHARES:
        a[f"dim_{b}"] = f[f"dim_{b}"]
    for q in PARITY_SHARES:
        a[f"parity_{q}"] = f[f"parity_{q}"]
    a["dry_preg_per_milking"] = f["dry_pregnant"] / m
    a["dry_open_per_milking"] = f["dry_open"] / m
    a["heifer_preg_per_milking"] = f["heifers_pregnant"] / m
    a["herd_per_milking"] = f["n_herd"] / m
    a["thi_m7"] = f["thi_mean"].rolling(7, min_periods=1).mean()
    a["thi_max_m7"] = f["thi_max"].rolling(7, min_periods=1).mean()
    a["rain_m7"] = f["rain_total_mm"].rolling(7, min_periods=1).mean()
    a["mastitis_28"] = 100 * f["mastitis_episodes"].rolling(28, min_periods=1).sum() / m
    a["udder_28"] = 100 * f["udder_teat_episodes"].rolling(28, min_periods=1).sum() / m
    a["blood_alarms_7"] = f["n_blood_alarms"].rolling(7, min_periods=1).sum() / m
    a["cond_alarms_7"] = f["n_conductivity_alarms"].rolling(7, min_periods=1).sum() / m
    return a.replace([np.inf, -np.inf], np.nan)


def _local_level(z: np.ndarray, q: float, r: float, score: np.ndarray | None = None):
    """Local-level Kalman filter on log litres per cow; NaN = no record that day."""
    n = len(z)
    level, var = np.full(n, np.nan), np.full(n, np.nan)
    a, p, ll = np.nan, np.nan, 0.0
    for t in range(n):
        if np.isnan(a):
            if np.isfinite(z[t]):
                a, p = z[t], r
        else:
            p += q
            if np.isfinite(z[t]):
                s = p + r
                e = z[t] - a
                if score is not None and score[t]:
                    ll -= 0.5 * (np.log(2 * np.pi * s) + e * e / s)
                k = p / s
                a, p = a + k * e, p * (1 - k)
        level[t], var[t] = a, p
    return level, var, ll


def fit_local_level(daily: pd.DataFrame, train_end: date) -> dict:
    """Noise variances by maximum likelihood on training days only."""
    z = np.log(daily["per_cow"].to_numpy(dtype=float))
    score = np.asarray(daily.index <= pd.Timestamp(train_end))
    best = (-np.inf, 1e-4, 1e-3)
    for q in np.logspace(-6, -1.5, 10):
        for r in np.logspace(-4, -1, 8):
            ll = _local_level(z, q, r, score)[2]
            if ll > best[0]:
                best = (ll, q, r)
    return {"q": float(best[1]), "r": float(best[2]), "loglik": float(best[0])}


def add_kalman(asof: pd.DataFrame, daily: pd.DataFrame, params: dict) -> pd.DataFrame:
    z = np.log(daily["per_cow"].to_numpy(dtype=float))
    level, var, _ = _local_level(z, params["q"], params["r"])
    a = asof.copy()
    a["kal_level"] = level
    a["kal_gap"] = level - np.log(a["pc_m7"])
    a["kal_sd"] = np.sqrt(var)
    return a


@dataclass
class Table:
    meta: pd.DataFrame
    X: pd.DataFrame
    starts: np.ndarray   # position of each origin in the daily frame


def build_table(daily: pd.DataFrame, asof: pd.DataFrame, grain: str, rolling: bool) -> Table:
    """Samples of one grain. ``rolling``: a window of ``TRAIN_WINDOW_DAYS`` from every day
    (training); otherwise calendar days / Monday weeks / months (scoring)."""
    idx = daily.index
    n = len(idx)
    if rolling or grain == "daily":
        starts = np.arange(1, n)
        lengths = np.full(len(starts), TRAIN_WINDOW_DAYS[grain])
    elif grain == "weekly":
        starts = np.flatnonzero(idx.weekday == 0)
        lengths = np.full(len(starts), 7)
    else:
        starts = np.flatnonzero(idx.day == 1)
        lengths = idx[starts].days_in_month.to_numpy()
    keep = (starts >= 1) & (starts + lengths - 1 < n)
    starts, lengths = starts[keep], lengths[keep]
    ends = starts + lengths - 1
    lit = daily["litres"].to_numpy(dtype=float)
    cs_l = np.concatenate([[0.0], np.cumsum(np.nan_to_num(lit))])
    cs_n = np.concatenate([[0], np.cumsum(np.isfinite(lit))])
    n_ok = cs_n[ends + 1] - cs_n[starts]
    with np.errstate(invalid="ignore", divide="ignore"):
        actual = np.where(n_ok > 0, (cs_l[ends + 1] - cs_l[starts]) / np.maximum(n_ok, 1), np.nan)
    X = asof.iloc[starts - 1].reset_index(drop=True)
    mid = idx[starts] + pd.to_timedelta((lengths - 1) / 2, unit="D")
    ang = 2 * np.pi * mid.dayofyear.to_numpy() / 365.25
    X["doy_sin"], X["doy_cos"], X["period_days"] = np.sin(ang), np.cos(ang), lengths
    drift = (X["milking_trend28"].fillna(0.0) / 28).to_numpy()
    X["drift_to_mid"] = np.clip(drift * (lengths + 1) / 2, -MAX_DRIFT, MAX_DRIFT)
    m_proj = X["milking"].to_numpy() * np.exp(X["drift_to_mid"].to_numpy())
    fresh = X["days_since_ok"].to_numpy() <= MAX_BASE_AGE_DAYS
    level = X["pc_m7"].fillna(X["pc_m28"]).to_numpy()
    base = np.where(fresh, level * m_proj, np.nan)
    pers_col = {"daily": "lit_last", "weekly": "lit_m7", "monthly": "lit_m28"}[grain]
    pers = X[pers_col].fillna(X["lit_m7"]).fillna(X["lit_last"]).to_numpy()
    kal = (np.exp(X["kal_level"].to_numpy()) * m_proj) if "kal_level" in X else np.full(len(X), np.nan)
    meta = pd.DataFrame({
        "grain": grain, "origin": idx[starts], "period_start": idx[starts],
        "period_end": idx[ends], "period_days": lengths, "actual": actual,
        "coverage": n_ok / lengths, "milking_projected": m_proj,
        "base": base, "persistence": np.where(fresh, pers, np.nan),
        "kalman": np.where(fresh, kal, np.nan),
    })
    meta["has_base"] = np.isfinite(meta["base"]) & (meta["base"] > 0) & np.isfinite(meta["persistence"])
    return Table(meta, X.drop(columns=["milking", "kal_level"], errors="ignore"), starts)


def sequences(daily: pd.DataFrame, starts: np.ndarray, base: np.ndarray,
              seq_len: int) -> np.ndarray:
    """(N, seq_len, 6) of the days before each origin: milk vs this row's base, recorded
    flag, milking vs the day before the origin, calvings and dry-offs per 100 cows, THI."""
    lit = daily["litres"].to_numpy(dtype=float)
    mk = daily["milking"].to_numpy(dtype=float)
    calv, dry = daily["calvings"].to_numpy(float), daily["dry_offs"].to_numpy(float)
    thi = daily["thi_mean"].to_numpy(float)
    pos = starts[:, None] - seq_len + np.arange(seq_len)[None, :]
    valid = pos >= 0
    p = np.clip(pos, 0, None)
    last = mk[starts - 1][:, None]
    with np.errstate(invalid="ignore", divide="ignore"):
        rel = np.log(lit[p] / base[:, None])
        m_rel = np.log(mk[p] / last)
        cv, dr = 100 * calv[p] / mk[p], 100 * dry[p] / mk[p]
    okf = np.isfinite(rel) & valid
    out = np.stack([np.where(okf, np.clip(rel, -1, 1), 0.0), okf.astype(float),
                    np.where(valid, np.nan_to_num(np.clip(m_rel, -1, 1)), 0.0),
                    np.where(valid, np.nan_to_num(cv), 0.0), np.where(valid, np.nan_to_num(dr), 0.0),
                    np.where(valid, np.nan_to_num((thi[p] - 74) / 5), 0.0)], axis=2)
    return out.astype(np.float32)


# ---------------------------------------------------------------- models

@dataclass
class HerdModels:
    train_end: date
    validation_end: date
    tables: dict[str, pd.DataFrame]                     # scoring rows per grain (+ block)
    predictions: dict[str, dict[str, np.ndarray]]       # model -> grain -> litres/day
    intervals: dict[str, dict[str, np.ndarray]] = field(default_factory=dict)
    features: dict[str, pd.DataFrame] = field(default_factory=dict)
    nets: dict[str, dict] = field(default_factory=dict)  # grain -> model -> (scaler, nets, cols)
    fitted: dict = field(default_factory=dict)


def block_labels(meta: pd.DataFrame, train_end: date, validation_end: date) -> np.ndarray:
    te, ve = pd.Timestamp(train_end), pd.Timestamp(validation_end)
    return np.select([meta["period_end"] <= te,
                      (meta["origin"] > te) & (meta["period_end"] <= ve),
                      meta["origin"] > ve], ["train", "validation", "test"], "straddle")


def recalibrate(meta: pd.DataFrame, pred: np.ndarray, grain: str) -> tuple[np.ndarray, np.ndarray]:
    """Walk-forward level correction: actual / predicted over the last scored periods
    that ended before each origin (at most ``RECAL_MAX_AGE_DAYS`` old)."""
    s = meta["scored"].to_numpy() & np.isfinite(pred)
    pe = meta["period_end"].to_numpy()[s]
    order = np.argsort(pe)
    pe, act, pr = pe[order], meta["actual"].to_numpy()[s][order], pred[s][order]
    cs_a, cs_p = np.concatenate([[0.0], np.cumsum(act)]), np.concatenate([[0.0], np.cumsum(pr)])
    o = meta["origin"].to_numpy()
    k = np.searchsorted(pe, o, side="left")
    lo = np.maximum(k - RECAL_LOOKBACK[grain],
                    np.searchsorted(pe, o - np.timedelta64(RECAL_MAX_AGE_DAYS, "D"), "left"))
    lo = np.minimum(lo, k)
    num, den = cs_a[k] - cs_a[lo], cs_p[k] - cs_p[lo]
    factor = np.where((k > lo) & (den > 0), num / np.where(den > 0, den, 1.0), 1.0)
    factor = np.clip(factor, *RECAL_BOUNDS)
    return pred * factor, factor


def _ensemble(make, inputs_fit, y, fit_idx, stop_idx, params, device, seeds, base, actual):
    nets, infos = [], []
    for s in seeds:
        net, info = _fit_module(make(), inputs_fit, y, fit_idx, stop_idx, params, device, s,
                                base, actual)
        nets.append(net)
        infos.append(info)
    return nets, infos


def _predict(nets, inputs, device) -> np.ndarray:
    return np.mean([predict_net(n, inputs, device) for n in nets], axis=0)


def fit_herd_models(daily: pd.DataFrame, train_end: date, validation_end: date,
                    params: dict | None = None, device: str = "cpu", seed: int = 17,
                    options: dict | None = None, min_coverage: float = 1.0,
                    grains: tuple[str, ...] = GRAINS, verbose: bool = False,
                    cow_preds: dict[str, pd.Series] | None = None) -> HerdModels:
    """Fit every candidate on periods ending by ``train_end`` and predict every calendar
    period of every grain. Inputs of a period use days before its origin only.

    ``cow_preds`` (notebook 08, optional): grain -> notebook 06's out-of-sample mean
    predicted litres per recorded cow, indexed by period start (``herd_cow_link``). It
    adds ``cow06_structural`` (that yield x projected milking cows) and ``torch_mlp_cow06``
    (the small network plus the gap between it and the herd's recent litres per cow),
    both NaN where no prediction exists. Without it nothing changes."""
    import torch

    params = {**DEFAULT_PARAMS, **(params or {})}
    opts = {**MODEL_OPTIONS, **(options or {})}
    device = resolve_device(device)
    MLP, GRUNet = _modules()
    t0 = time.perf_counter()
    asof = asof_features(daily)
    fitted: dict = {"params": params, "options": opts, "device": device}
    if opts["use_kalman"]:
        kp = fit_local_level(daily, train_end)
        asof = add_kalman(asof, daily, kp)
        fitted["kalman"] = kp
    out = HerdModels(train_end, validation_end, {}, {}, fitted=fitted)
    seeds = [seed + 101 * i for i in range(opts["ensemble"])]
    te = pd.Timestamp(train_end)

    def put(model, grain, pred):
        out.predictions.setdefault(model, {})[grain] = np.asarray(pred, dtype=float)

    for grain in grains:
        tr = build_table(daily, asof, grain, rolling=True)
        sc = build_table(daily, asof, grain, rolling=False)
        m = tr.meta
        use = (m["has_base"] & (m["coverage"] >= min_coverage) & (m["period_end"] <= te)
               & (m["actual"] > 0)).to_numpy()
        keep = sc.meta["has_base"].to_numpy()
        meta = sc.meta[keep].reset_index(drop=True)
        meta["block"] = block_labels(meta, train_end, validation_end)
        meta["scored"] = (meta["coverage"] >= min_coverage) & (meta["actual"] > 0)
        out.tables[grain] = meta
        Xs = sc.X[keep].reset_index(drop=True)
        out.features[grain] = Xs
        put("persistence", grain, meta["persistence"])
        put("herd_structural", grain, meta["base"])
        if opts["use_kalman"]:
            put("herd_kalman", grain, meta["kalman"].fillna(meta["base"]))
        cow_s = None
        if cow_preds is not None and grain in cow_preds:
            cow_s = cow_preds[grain].reindex(meta["period_start"]).to_numpy(dtype=float)
            put("cow06_structural", grain, cow_s * meta["milking_projected"].to_numpy())
            fitted.setdefault("cow06_periods", {})[grain] = int(np.isfinite(cow_s).sum())
        n_train = int(use.sum())
        fitted.setdefault("train_rows", {})[grain] = n_train
        if n_train < 20:
            if verbose:
                print(f"  {grain}: only {n_train} training windows; networks skipped")
            continue
        Xt, mt = tr.X[use].reset_index(drop=True), m[use].reset_index(drop=True)
        base_t, act_t = mt["base"].to_numpy(), mt["actual"].to_numpy()
        y = np.clip(np.log(act_t / base_t), -CLIP, CLIP)
        weeks = ((mt["origin"] - mt["origin"].min()).dt.days // 7).to_numpy()
        stop = weeks % STOP_EVERY_WEEKS == STOP_EVERY_WEEKS - 1
        fit_idx, stop_idx = np.flatnonzero(~stop), np.flatnonzero(stop)
        base_s = meta["base"].to_numpy()
        cols = [c for c in Xt.columns]
        nomove = [c for c in cols if not any(c in FEATURE_FAMILIES[f] for f in MOVEMENT_FAMILIES)]
        nets_g = out.nets.setdefault(grain, {})

        def mlp_family(name, hidden, use_cols, n_seeds):
            sc_ = _Scaler.fit(Xt[use_cols])
            xt, xs = sc_.transform(Xt[use_cols]), sc_.transform(Xs[use_cols])
            nets, infos = _ensemble(lambda: MLP(xt.shape[1], tuple(hidden), params["dropout"]),
                                    [xt], y, fit_idx, stop_idx, params, device, n_seeds,
                                    base_t, act_t)
            put(name, grain, base_s * np.exp(np.clip(_predict(nets, [xs], device), -CLIP, CLIP)))
            nets_g[name] = (sc_, nets, use_cols)
            fitted.setdefault("epochs", {})[(grain, name)] = (infos[0]["best_epoch"], infos[0]["epochs"])

        for name in opts["networks"]:
            hidden = params["hidden_small"] if name == "torch_mlp_small" else params["hidden_large"]
            mlp_family(name, hidden, cols, seeds)
        if opts["use_ablation"]:
            mlp_family("torch_mlp_nomove", params["hidden_small"], nomove, seeds)
        if cow_s is not None:
            cow_t = cow_preds[grain].reindex(mt["period_start"]).to_numpy(dtype=float)
            with np.errstate(invalid="ignore", divide="ignore"):
                gap_t = np.log(cow_t / Xt["pc_m7"].fillna(Xt["pc_m28"]).to_numpy())
                gap_s = np.log(cow_s / Xs["pc_m7"].fillna(Xs["pc_m28"]).to_numpy())
            have = np.isfinite(gap_t)
            fi, si = fit_idx[have[fit_idx]], stop_idx[have[stop_idx]]
            fitted.setdefault("cow06_train_rows", {})[grain] = len(fi) + len(si)
            if len(fi) >= 20:
                Xt2, Xs2 = Xt[cols].assign(cow06_gap=gap_t), Xs[cols].assign(cow06_gap=gap_s)
                sc_ = _Scaler.fit(Xt2[have])
                xt, xs = sc_.transform(Xt2), sc_.transform(Xs2)
                nets, infos = _ensemble(lambda: MLP(xt.shape[1], tuple(params["hidden_small"]),
                                                    params["dropout"]),
                                        [xt], y, fi, si, params, device, seeds, base_t, act_t)
                p = base_s * np.exp(np.clip(_predict(nets, [xs], device), -CLIP, CLIP))
                put("torch_mlp_cow06", grain, np.where(np.isfinite(gap_s), p, np.nan))
                nets_g["torch_mlp_cow06"] = (sc_, nets, cols + ["cow06_gap"])
                fitted.setdefault("epochs", {})[(grain, "torch_mlp_cow06")] = (
                    infos[0]["best_epoch"], infos[0]["epochs"])
        if opts["use_gru"]:
            sc_ = _Scaler.fit(Xt[cols])
            xt, xs = sc_.transform(Xt[cols]), sc_.transform(Xs[cols])
            qt = sequences(daily, tr.starts[use], base_t, opts["seq_len"])
            qs = sequences(daily, sc.starts[keep], base_s, opts["seq_len"])
            gseeds = seeds[:max(1, opts["gru_seeds"])]
            nets, infos = _ensemble(lambda: GRUNet(xt.shape[1], qt.shape[2], opts["gru_hidden"],
                                                   params["dropout"]),
                                    [xt, qt], y, fit_idx, stop_idx, params, device, gseeds,
                                    base_t, act_t)
            put("torch_gru", grain, base_s * np.exp(np.clip(_predict(nets, [xs, qs], device),
                                                            -CLIP, CLIP)))
            fitted.setdefault("epochs", {})[(grain, "torch_gru")] = (infos[0]["best_epoch"], infos[0]["epochs"])
        if opts["use_quantile"]:
            sc_ = _Scaler.fit(Xt[cols])
            xt, xs = sc_.transform(Xt[cols]), sc_.transform(Xs[cols])
            torch.manual_seed(seed)
            net, info = _fit_module(MLP(xt.shape[1], tuple(params["hidden_small"]),
                                        params["dropout"], n_out=len(QUANTILES)),
                                    [xt], y, fit_idx, stop_idx, params, device, seed,
                                    base_t, act_t, quantiles=QUANTILES)
            qp = np.sort(np.clip(predict_net(net, [xs], device), -CLIP, CLIP), axis=1)
            put("torch_q50", grain, base_s * np.exp(qp[:, 1]))
            out.intervals.setdefault("torch_q50", {})[grain] = base_s[:, None] * np.exp(qp[:, [0, 2]])
            fitted.setdefault("epochs", {})[(grain, "torch_q50")] = (info["best_epoch"], info["epochs"])
        if verbose:
            print(f"  {grain}: {n_train:,} training windows, {int(meta['scored'].sum()):,} "
                  f"scored periods ({time.perf_counter() - t0:,.0f}s)")
    # Walk-forward recalibrated variant of every candidate except persistence.
    for model in [k for k in list(out.predictions) if k != "persistence"]:
        for grain, pred in list(out.predictions[model].items()):
            p, factor = recalibrate(out.tables[grain], pred, grain)
            put(f"{model}_recal", grain, p)
            if model in out.intervals and grain in out.intervals[model]:
                out.intervals.setdefault(f"{model}_recal", {})[grain] = (
                    out.intervals[model][grain] * factor[:, None])
    fitted["seconds"] = time.perf_counter() - t0
    return out


# ---------------------------------------------------------------- scoring

def _metrics(actual: np.ndarray, pred: np.ndarray, pers: np.ndarray) -> dict:
    e = pred - actual
    rel = np.abs(e) / actual
    mae, mae_p = np.mean(np.abs(e)), np.mean(np.abs(pers - actual))
    ss = np.sum((actual - actual.mean()) ** 2)
    return {"periods": len(actual), "actual_sum": actual.sum(), "abs_err_sum": np.abs(e).sum(),
            "accuracy_pct": 100 - 100 * np.abs(e).sum() / actual.sum(),
            "within_5pct": 100 * np.mean(rel <= 0.05), "within_10pct": 100 * np.mean(rel <= 0.10),
            "mae_litres_per_day": mae, "bias_pct": 100 * e.sum() / actual.sum(),
            "skill_vs_persistence_pct": 100 * (1 - mae / mae_p) if mae_p > 0 else np.nan,
            "r2": 1 - np.sum(e ** 2) / ss if ss > 0 else np.nan}


def score_herd(models: HerdModels, blocks: tuple[str, ...] = ("validation",),
               windows: dict[str, tuple[date, date]] | None = None) -> pd.DataFrame:
    """Every candidate on the same scored periods (litres per day). ``windows`` scores
    named date ranges (by period start) inside ``blocks`` instead of the whole block."""
    rows = []
    for grain, meta in models.tables.items():
        base_mask = meta["block"].isin(blocks).to_numpy() & meta["scored"].to_numpy()
        named = windows or {"+".join(blocks): (None, None)}
        for label, (a, b) in named.items():
            mask = base_mask.copy()
            if a is not None:
                mask &= ((meta["period_start"] >= pd.Timestamp(a))
                         & (meta["period_start"] <= pd.Timestamp(b))).to_numpy()
            preds = {k: v[grain] for k, v in models.predictions.items() if grain in v}
            mask &= np.all([np.isfinite(p) for p in preds.values()], axis=0)
            if not mask.any():
                continue
            act, pers = meta["actual"].to_numpy()[mask], preds["persistence"][mask]
            for model, p in preds.items():
                rows.append({"block": label, "grain": grain, "model": model,
                             **_metrics(act, p[mask], pers)})
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["block", "grain", "accuracy_pct"],
                           ascending=[True, True, False]).reset_index(drop=True)


def pool_metrics(frames: list[pd.DataFrame], label: str = "pooled") -> pd.DataFrame:
    """Pool scores across blocks/windows, weighting errors by litres."""
    allm = pd.concat([f for f in frames if len(f)], ignore_index=True)
    allm["w10"] = allm["within_10pct"] * allm["periods"]
    g = allm.groupby(["grain", "model"], as_index=False).agg(
        periods=("periods", "sum"), actual_sum=("actual_sum", "sum"),
        abs_err_sum=("abs_err_sum", "sum"), w10=("w10", "sum"), parts=("block", "nunique"))
    g["accuracy_pct"] = 100 - 100 * g["abs_err_sum"] / g["actual_sum"]
    g["within_10pct"] = g["w10"] / g["periods"]
    g["block"] = label
    return (g.drop(columns="w10").sort_values(["grain", "accuracy_pct"], ascending=[True, False])
            .reset_index(drop=True))


def pool_common_parts(frames: list[pd.DataFrame], label: str = "pooled") -> pd.DataFrame:
    """``pool_metrics`` per grain over only the parts (validation, windows) in which every
    candidate of that grain was scored, so no model is ranked on an easier subset."""
    out = []
    parts = [f for f in frames if len(f)]
    for grain in sorted({g for f in parts for g in f["grain"].unique()}):
        sub = [f[f["grain"] == grain] for f in parts if (f["grain"] == grain).any()]
        everyone = set().union(*(set(f["model"]) for f in sub))
        common = [f for f in sub if set(f["model"]) == everyone]
        if not common:  # no part has every model: keep models present in every part
            shared = set.intersection(*(set(f["model"]) for f in sub))
            common = [f[f["model"].isin(shared)] for f in sub]
        out.append(pool_metrics(common, label))
    return pd.concat(out, ignore_index=True)


def add_blend(models: HerdModels, winners: dict[str, str], block: str = "validation") -> dict:
    """Mix each grain's winner with persistence; the weight is fitted on ``block``."""
    spec = {}
    for grain, model in winners.items():
        meta = models.tables[grain]
        mask = (meta["block"] == block).to_numpy() & meta["scored"].to_numpy()
        p, q = models.predictions[model][grain], models.predictions["persistence"][grain]
        best = (np.inf, 1.0)
        if mask.any():
            act = meta["actual"].to_numpy()[mask]
            for w in np.linspace(0, 1, 11):
                err = np.abs(w * p[mask] + (1 - w) * q[mask] - act).sum()
                if err < best[0] - 1e-9:
                    best = (err, float(w))
        spec[grain] = (model, best[1])
    apply_blend(models, spec)
    return spec


def apply_blend(models: HerdModels, spec: dict) -> None:
    for grain, (model, w) in spec.items():
        if model in models.predictions and grain in models.predictions[model]:
            p = models.predictions[model][grain]
            q = models.predictions["persistence"][grain]
            models.predictions.setdefault("blend", {})[grain] = w * p + (1 - w) * q


def interval_coverage(models: HerdModels, block: str = "test") -> pd.DataFrame:
    rows = []
    for model, by_grain in models.intervals.items():
        for grain, iv in by_grain.items():
            meta = models.tables[grain]
            mask = (meta["block"] == block).to_numpy() & meta["scored"].to_numpy()
            if not mask.any():
                continue
            a = meta["actual"].to_numpy()[mask]
            lo, hi = iv[mask, 0], iv[mask, 1]
            rows.append({"model": model, "grain": grain, "periods": int(mask.sum()),
                         "inside_10_90_pct": 100 * np.mean((a >= lo) & (a <= hi)),
                         "mean_width_pct": 100 * np.mean((hi - lo) / a)})
    return pd.DataFrame(rows)


def movement_importance(models: HerdModels, model: str = "torch_mlp_small",
                        block: str = "validation", repeats: int = 5,
                        seed: int = 17) -> pd.DataFrame:
    """Accuracy lost when one feature family is shuffled across periods (higher = the
    network relies on it more). Uses the stored network; nothing is refitted."""
    rng = np.random.default_rng(seed)
    device = models.fitted["device"]
    rows = []
    for grain, by_model in models.nets.items():
        if model not in by_model:
            continue
        scaler, nets, cols = by_model[model]
        meta, X = models.tables[grain], models.features[grain]
        mask = (meta["block"] == block).to_numpy() & meta["scored"].to_numpy()
        if mask.sum() < 3:
            continue
        Xb, base = X[mask].reset_index(drop=True), meta["base"].to_numpy()[mask]
        act = meta["actual"].to_numpy()[mask]

        def acc(frame):
            p = base * np.exp(np.clip(_predict(nets, [scaler.transform(frame[cols])], device),
                                      -CLIP, CLIP))
            return 100 - 100 * np.abs(p - act).sum() / act.sum()

        ref = acc(Xb)
        for fam, fcols in FEATURE_FAMILIES.items():
            use = [c for c in fcols if c in cols]
            if not use:
                continue
            drops = []
            for _ in range(repeats):
                Xp = Xb.copy()
                Xp[use] = Xb[use].to_numpy()[rng.permutation(len(Xb))]
                drops.append(ref - acc(Xp))
            rows.append({"grain": grain, "family": fam, "features": len(use),
                         "accuracy_pct": ref, "accuracy_drop_pp": float(np.mean(drops))})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- windows and tuning

def equal_day_cuts(daily: pd.DataFrame, end: date, n_blocks: int) -> list[pd.Timestamp]:
    """Last date of each of ``n_blocks`` blocks with equal numbers of recorded days."""
    d = daily.index[daily["ok"].to_numpy() & (daily.index <= pd.Timestamp(end))]
    if len(d) < n_blocks:
        raise ValueError("not enough recorded days for the windows")
    return [d[int(np.ceil(len(d) * k / n_blocks)) - 1] for k in range(1, n_blocks + 1)]


def expanding_windows(daily: pd.DataFrame, end: date, n_blocks: int, fit_kwargs: dict,
                      verbose: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Window k trains on blocks 1..k and is scored on block k+1 (all candidates)."""
    cuts = equal_day_cuts(daily, end, n_blocks)
    metrics, cond = [], []
    for k in range(1, n_blocks):
        tr_end, te_end = cuts[k - 1].date(), cuts[k].date()
        models = fit_herd_models(daily, tr_end, te_end, **fit_kwargs)
        m = score_herd(models, ("validation",))
        if len(m):
            m["block"] = f"window_{k}"
            m["window"] = k
            metrics.append(m)
        part = daily[(daily.index > pd.Timestamp(tr_end)) & (daily.index <= pd.Timestamp(te_end))]
        cond.append({"window": k, "train_end": tr_end, "test_start": tr_end + timedelta(days=1),
                     "test_end": te_end, "train_recorded_days":
                         int(daily.loc[:pd.Timestamp(tr_end), "ok"].sum()),
                     "test_recorded_days": int(part["ok"].sum()),
                     "test_mean_litres_per_day": part["litres"].mean(),
                     "test_mean_milking": part["milking"].mean(),
                     "test_calvings": part["calvings"].sum(), "test_dry_offs": part["dry_offs"].sum()})
        if verbose:
            print(f"window {k}: train to {tr_end}, test to {te_end}")
    return (pd.concat(metrics, ignore_index=True) if metrics else pd.DataFrame(),
            pd.DataFrame(cond))


def window_summary(metrics: pd.DataFrame, value: str = "accuracy_pct") -> pd.DataFrame:
    return metrics.pivot_table(index=["grain", "model"], columns="window", values=value).round(2)


def tune_herd(daily: pd.DataFrame, train_end: date, n_trials: int = 12, device: str = "cpu",
              seed: int = 17, fixed: dict | None = None, min_coverage: float = 1.0,
              cuts: tuple[float, ...] = (0.6, 0.75, 0.9),
              verbose: bool = False) -> tuple[dict, pd.DataFrame]:
    """Random search for ``torch_mlp_large`` on expanding folds inside the training block.
    Trial 0 is the default; the score is mean accuracy over folds and grains."""
    rng = np.random.default_rng(seed)
    d = daily.index[daily["ok"].to_numpy() & (daily.index <= pd.Timestamp(train_end))]
    points = [d[int(len(d) * c) - 1].date() for c in cuts] + [pd.Timestamp(train_end).date()]
    folds = list(zip(points[:-1], points[1:]))
    fixed = fixed or {}
    trials = []
    for t in range(n_trials):
        params = dict(DEFAULT_PARAMS) if t == 0 else {
            k: v[rng.integers(len(v))] for k, v in SEARCH_SPACE.items()}
        params = {**DEFAULT_PARAMS, **params, **fixed}
        scores = []
        for tr_end, va_end in folds:
            m = fit_herd_models(daily, tr_end, va_end, params, device, seed,
                                {"ensemble": 1, "use_gru": False, "use_quantile": False,
                                 "use_ablation": False, "networks": ("torch_mlp_large",)},
                                min_coverage)
            s = score_herd(m, ("validation",))
            s = s[s["model"] == "torch_mlp_large"]
            scores += list(s["accuracy_pct"])
        trials.append({"trial": t, **{k: params[k] for k in SEARCH_SPACE},
                       "folds_scored": len(scores),
                       "mean_accuracy_pct": float(np.mean(scores)) if scores else np.nan})
        if verbose:
            print(f"trial {t}: {trials[-1]['mean_accuracy_pct']:.2f}%")
    table = pd.DataFrame(trials).sort_values("mean_accuracy_pct", ascending=False,
                                             na_position="last").reset_index(drop=True)
    best = table.iloc[0]
    chosen = {**DEFAULT_PARAMS, **{k: best[k] for k in SEARCH_SPACE}, **fixed}
    chosen["batch_size"] = int(chosen["batch_size"])
    chosen["hidden_large"] = tuple(chosen["hidden_large"])
    return chosen, table


# ---------------------------------------------------------------- charts (aggregate)

def _broken(x: pd.Series, y, grain: str) -> tuple[pd.Series, np.ndarray]:
    """Insert a NaN where periods are missing so lines never bridge the gap."""
    x = pd.Series(pd.to_datetime(x)).reset_index(drop=True)
    y = np.asarray(y, dtype=float)
    step = {"daily": 3, "weekly": 21, "monthly": 70}[grain]
    jumps = np.flatnonzero(x.diff().dt.days.to_numpy()[1:] > step) + 1
    if not len(jumps):
        return x, y
    xs = np.insert(x.to_numpy(), jumps, x.to_numpy()[jumps - 1] + np.timedelta64(1, "D"))
    ys = np.insert(y, jumps, np.nan, axis=0)
    return pd.Series(xs), ys


def plot_herd_forecast(models: HerdModels, model_by_grain: dict[str, str], path,
                       gap: tuple[date, date] | None, title: str,
                       show_blocks: tuple[str, ...] = ("validation", "test")):
    """Selected model per grain. Only periods in ``show_blocks`` are drawn as forecasts;
    periods the model was trained on are greyed out as "training fit (in-sample)", and
    test periods are left out entirely when "test" is not in ``show_blocks``. The block
    boundaries are the model's own ``train_end`` / ``validation_end``."""
    import matplotlib.pyplot as plt

    te, ve = pd.Timestamp(models.train_end), pd.Timestamp(models.validation_end)
    grains = [g for g in GRAINS if g in model_by_grain and g in models.tables]
    fig, axes = plt.subplots(len(grains), 1, figsize=(15, 3.6 * len(grains)), squeeze=False)
    for ax, grain in zip(axes[:, 0], grains):
        meta, model = models.tables[grain], model_by_grain[grain]
        show = meta["block"].isin(show_blocks).to_numpy()
        hidden = ((meta["period_end"] > ve).to_numpy() if "test" not in show_blocks
                  else np.zeros(len(meta), dtype=bool))
        fit = ~show & ~hidden
        s = meta["scored"].to_numpy() & ~hidden
        x = meta["period_start"]
        x_end = x[~hidden].max()

        def only(values, mask):
            v = np.asarray(values, dtype=float).copy()
            v[~mask] = np.nan
            return _broken(x, v, grain)

        ax.axvspan(x.min(), te, color="#f3f4f6", alpha=0.9, label="training (in-sample)")
        if ve > te:
            ax.axvspan(te, min(ve, x_end), color="#fde68a", alpha=0.4, label="validation")
        if "test" in show_blocks and x_end > ve:
            ax.axvspan(ve, x_end, color="#bfdbfe", alpha=0.25, label="test")
        if gap is not None and pd.Timestamp(gap[0]) < x_end:
            ax.axvspan(pd.Timestamp(gap[0]), min(pd.Timestamp(gap[1]), x_end), color="#d1d5db",
                       alpha=0.8, label="recording gap (excluded)")
        ax.plot(x[s], meta["actual"][s], ".", ms=3 if grain == "daily" else 6, color="black",
                label="actual (recorded)")
        pred = models.predictions[model][grain]
        ax.plot(*only(pred, fit), lw=0.9, ls="--", color="#94a3b8",
                label=f"{model}: training fit (in-sample, not a test)")
        ax.plot(*only(models.predictions["persistence"][grain], show), lw=0.8,
                color="#6b7280", label="persistence")
        ax.plot(*only(pred, show), lw=1.4, color="#1f77b4", label=f"{model}: forecast")
        iv = models.intervals.get(model, {}).get(grain)
        if iv is not None:
            xb, lo = only(iv[:, 0], show)
            _, hi = only(iv[:, 1], show)
            ax.fill_between(xb, lo, hi, color="#1f77b4", alpha=0.15, label="10-90% range")
        ax.set_xlim(x.min() - pd.Timedelta(days=15), x_end + pd.Timedelta(days=15))
        ax.set_title(f"{grain}: herd milk, litres per day", fontsize=10)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=7, ncol=6, loc="upper left")
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    return fig


def plot_herd_movement(daily: pd.DataFrame, path, gap: tuple[date, date] | None = None):
    """Monthly herd movement next to herd milk (aggregate)."""
    import matplotlib.pyplot as plt

    mth = daily.resample("MS").agg({"milking": "mean", "calvings": "sum", "dry_offs": "sum",
                                    "exits": "sum", "litres": "mean"})
    fig, (a1, a2, a3) = plt.subplots(3, 1, figsize=(15, 9), sharex=True)
    a1.plot(mth.index, mth["milking"], color="#1f77b4")
    a1.set_title("Milking cows (monthly mean)", fontsize=10)
    w = 20
    a2.bar(mth.index, mth["calvings"], width=w, color="#16a34a", label="calvings (in)")
    a2.bar(mth.index, -mth["dry_offs"], width=w, color="#f59e0b", label="dry-offs (out)")
    a2.bar(mth.index, -mth["exits"], width=w, bottom=-mth["dry_offs"], color="#dc2626",
           label="exits (out)")
    a2.axhline(0, color="black", lw=0.6)
    a2.set_title("Herd movement per month", fontsize=10)
    a2.legend(fontsize=8)
    a3.plot(mth.index, mth["litres"], color="black")
    a3.set_title("Herd milk, mean litres per recorded day (clean target)", fontsize=10)
    for ax in (a1, a2, a3):
        ax.grid(alpha=0.3)
        if gap is not None:
            ax.axvspan(pd.Timestamp(gap[0]), pd.Timestamp(gap[1]), color="#e5e7eb", alpha=0.8)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    return fig


def gap_for(scope: str) -> tuple[date, date]:
    return DATA_SCOPES[scope]
