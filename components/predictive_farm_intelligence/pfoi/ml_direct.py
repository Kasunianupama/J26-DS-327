"""Direct multi-horizon machine-learning forecaster (experiment, not a published model).

A pure ML alternative to the herd engine + lactation curve: one LightGBM model per
series, pooled over grains and horizons (horizon enters as ``lead_days`` and
``period_days``), on the origin-known features of ``ml_features``. A ridge regression on
the same features is the linear sanity check.

Targets (so the trees never need to extrapolate a level):
* milk: log(litres per day in the period / mean litres per day over the 28 days before
  the origin); trained only on periods from the source in use at the origin;
* stocks: log((period mean + 1) / (count on the day before the origin + 1));
* events: Poisson counts, boosted from the trailing 365-day rate x period days.

Rolling origin: the models are refitted every ``refit_months`` on rows whose target
period had ended by the refit date (and whose origin is before it), with recency weights.
Forecasts at an origin use the most recent refit on or before it, so no label from
the origin onward is ever used. Intervals come from each model's own past errors
(``error_tools.add_intervals``), as for every other model. Herd level only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable

import numpy as np
import pandas as pd

from .backtest_herd import TEST_START, persistence, ts_benchmarks
from .backtest_milk import _target_frame, benchmark_forecasts
from .data import DATA_START, add_months
from .error_tools import add_intervals
from .ml_features import (
    DEFAULT_SERIES, MILK, MIN_HISTORY_DAYS, build_table, daily_frame, feature_group,
    feature_origins, load_snapshots, scored,
)
from .periods import HORIZONS

MODELS = ("ml_lgbm", "ml_ridge")
VERSION = "pfoi-1.4.0-dev"


@dataclass(frozen=True)
class MLConfig:
    """Fixed before any real-data run; change only with a new tag."""
    refit_months: int = 3
    half_life_days: float = 730.0     # recency weight of training rows
    min_train: int = 200              # rows per series needed to fit
    pipeline: bool = True             # composition and pregnancy-pipeline features
    n_estimators: int = 300
    learning_rate: float = 0.03
    num_leaves: int = 15
    min_child_samples: int = 40
    subsample: float = 0.8
    colsample: float = 0.8
    ridge_alpha: float = 10.0
    seed: int = 17

    def tag(self) -> str:
        return (f"ml_r{self.refit_months}_hl{self.half_life_days:g}"
                + ("" if self.pipeline else "_nopipe"))


def refit_date(origin: date, every: int) -> date:
    """Latest refit date on or before ``origin`` (first day of a block of ``every`` months)."""
    return date(origin.year, ((origin.month - 1) // every) * every + 1, 1)


def training_mask(meta: pd.DataFrame, refit: date) -> pd.Series:
    """Rows whose origin is before the refit date and whose target period ended by then."""
    return (pd.to_datetime(meta["origin"]) < pd.Timestamp(refit)) & \
        (pd.to_datetime(meta["period_end"]) <= pd.Timestamp(refit))


def transform(meta: pd.DataFrame) -> np.ndarray:
    """Training target per kind (events: the count itself, used with a Poisson objective)."""
    a, b = meta["actual"].to_numpy(float), meta["base"].to_numpy(float)
    days = (pd.to_datetime(meta["period_end"]) - pd.to_datetime(meta["period_start"])).dt.days.to_numpy()
    kind = meta["kind"].to_numpy()
    y = np.where(kind == "milk", np.log(np.maximum(a / days, 1e-9) / b),
                 np.where(kind == "stock", np.log((a + 1) / (b + 1)), a))
    return y


def inverse(meta: pd.DataFrame, p: np.ndarray, model: str) -> np.ndarray:
    """Model output back to litres (period total), animals (period mean) or event counts."""
    b = meta["base"].to_numpy(float)
    days = (pd.to_datetime(meta["period_end"]) - pd.to_datetime(meta["period_start"])).dt.days.to_numpy()
    kind = meta["kind"].to_numpy()
    if model == "ml_lgbm":
        event = b * np.exp(p)  # raw score on top of log(base) init score
    else:
        event = np.exp(p) * (b + 0.5) - 0.5
    out = np.where(kind == "milk", np.exp(p) * b * days,
                   np.where(kind == "stock", np.exp(p) * (b + 1) - 1, event))
    return np.maximum(out, 0.0)


def _lgbm(cfg: MLConfig, event: bool):
    from lightgbm import LGBMRegressor

    return LGBMRegressor(objective="poisson" if event else "regression", n_estimators=cfg.n_estimators,
                         learning_rate=cfg.learning_rate, num_leaves=cfg.num_leaves,
                         min_child_samples=cfg.min_child_samples, subsample=cfg.subsample,
                         subsample_freq=1, colsample_bytree=cfg.colsample, reg_lambda=1.0,
                         random_state=cfg.seed, deterministic=True, force_row_wise=True,
                         n_jobs=1, verbose=-1)


def _ridge(cfg: MLConfig):
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    return make_pipeline(SimpleImputer(strategy="median", add_indicator=True,
                                       keep_empty_features=True),
                         StandardScaler(), Ridge(alpha=cfg.ridge_alpha))


def fit_predict(meta_tr: pd.DataFrame, X_tr: pd.DataFrame, meta_q: pd.DataFrame, X_q: pd.DataFrame,
                refit: date, cfg: MLConfig, explain: bool = False) -> tuple[dict, pd.DataFrame | None]:
    """Forecasts of both models for the query rows of one series; optional SHAP by feature."""
    event = (meta_tr["kind"] == "event").all()
    age = (pd.Timestamp(refit) - pd.to_datetime(meta_tr["origin"])).dt.days.to_numpy(float)
    w = 0.5 ** (age / cfg.half_life_days)
    y = transform(meta_tr)
    out, contrib = {}, None

    if event and not (y > 0).any():
        # No event at all in the training rows: Poisson boosting is undefined, so the
        # forecast is the trailing rate itself (raw score 0); the caller counts it.
        out["ml_lgbm"] = inverse(meta_q, np.zeros(len(meta_q)), "ml_lgbm")
    else:
        gb = _lgbm(cfg, event)
        if event:
            gb.fit(X_tr, y, sample_weight=w, init_score=np.log(meta_tr["base"].to_numpy(float)))
        else:
            gb.fit(X_tr, y, sample_weight=w)
        p = gb.predict(X_q, raw_score=event)
        out["ml_lgbm"] = inverse(meta_q, p, "ml_lgbm")
        if explain:
            c = gb.predict(X_q, pred_contrib=True)  # TreeSHAP: features + bias = raw score
            contrib = pd.DataFrame(c, columns=[*X_q.columns, "_bias"], index=X_q.index)

    if event:
        y_r = np.log((meta_tr["actual"].to_numpy(float) + 0.5) / (meta_tr["base"].to_numpy(float) + 0.5))
    else:
        y_r = y
    rg = _ridge(cfg).fit(X_tr, y_r, ridge__sample_weight=w)
    # A linear model can extrapolate far outside the log ratios it has seen, and exp() then
    # explodes; keep it inside the range of its own training targets.
    out["ml_ridge"] = inverse(meta_q, np.clip(rg.predict(X_q), y_r.min(), y_r.max()), "ml_ridge")
    return out, contrib


def explain_groups(contrib: pd.DataFrame) -> pd.DataFrame:
    """SHAP contributions summed into feature groups (plus the bias); rows still add up to
    the model's raw score exactly."""
    groups = {c: ("baseline" if c == "_bias" else feature_group(c)) for c in contrib.columns}
    return contrib.T.groupby(pd.Series(groups)).sum().T


@dataclass
class MLResult:
    errors: pd.DataFrame
    importance: pd.DataFrame
    notes: pd.DataFrame


def _benchmarks(source_frames, meta_q: pd.DataFrame, origins_by_grain: dict, score_until: date) -> pd.DataFrame:
    """Persistence, seasonal naive, ETS and SARIMA from the existing backtest code."""
    panel, t = source_frames
    dates = pd.to_datetime(panel["date"]).dt.date
    rows = []
    for (origin, grain), g in meta_q.groupby(["origin", "grain"]):
        horizons = HORIZONS[grain]
        if MILK in set(g["series"]):
            for model, h, v in benchmark_forecasts(t, origin, grain, horizons):
                rows.append((origin, grain, h, MILK, model, v))
        herd = set(g["series"]) - {MILK}
        if herd and grain != "daily":
            past = panel.loc[dates < origin]
            pers = persistence(past, origin, grain, horizons)
            for r in pers.itertuples(index=False):
                if r.series in herd:
                    rows.append((origin, grain, r.horizon, r.series, "persistence", r.value))
            if grain == "monthly":
                for r in ts_benchmarks(past, origin, horizons).itertuples(index=False):
                    if r.series in herd:
                        rows.append((origin, grain, r.horizon, r.series, r.model, r.value))
    return pd.DataFrame(rows, columns=["origin", "grain", "horizon", "series", "model", "forecast"])


def run_ml_backtest(source, engine_cfg, ml_cfg: MLConfig, origins_by_grain: dict[str, list[date]],
                    score_until: date = TEST_START, series: tuple[str, ...] = DEFAULT_SERIES,
                    benchmarks: bool = True,
                    progress: Callable[[str], None] | None = None) -> MLResult:
    """Score ``origins_by_grain`` ({'monthly': [...], 'weekly': [...]}); weekly origins
    also score daily horizons. Only data before ``score_until`` is read."""
    say = progress or (lambda msg: None)
    panel = source.panel_daily(DATA_START, score_until)
    target = source.target_daily(DATA_START, score_until)
    f = daily_frame(panel, target)
    first = (pd.Timestamp(DATA_START) + timedelta(days=MIN_HISTORY_DAYS)).date()
    origins = feature_origins(first, score_until)
    snaps = None
    if ml_cfg.pipeline:
        say(f"loading pregnancy and composition snapshots for {len(origins)} origins")
        snaps = load_snapshots(source, origins, engine_cfg)
    say("building the feature table")
    meta, X = build_table(f, origins, tuple(series), snaps, score_until)
    want = {(o, g) for og, os_ in origins_by_grain.items()
            for o in os_ for g in ({"monthly": ("monthly",), "weekly": ("weekly", "daily")}[og])}
    is_query = scored(meta) & pd.Series([(o, g) in want for o, g in zip(meta["origin"], meta["grain"])],
                                        index=meta.index)
    refits = sorted({refit_date(o, ml_cfg.refit_months) for o in meta.loc[is_query, "origin"]})
    preds, imps, notes = [], [], {}
    for i, refit in enumerate(refits):
        say(f"refit {i + 1}/{len(refits)} ({refit})")
        nxt = add_months(refit, ml_cfg.refit_months)
        in_block = is_query & (pd.to_datetime(meta["origin"]) >= pd.Timestamp(refit)) & \
            (pd.to_datetime(meta["origin"]) < pd.Timestamp(nxt))
        train = training_mask(meta, refit) & meta["same_source"].astype(bool)
        for s in series:
            q = in_block & (meta["series"] == s)
            if not q.any():
                continue
            tr = train & (meta["series"] == s)
            if tr.sum() < ml_cfg.min_train:
                notes[f"{s}: too few training rows"] = notes.get(f"{s}: too few training rows", 0) + int(q.sum())
                continue
            out, contrib = fit_predict(meta[tr], X[tr], meta[q], X[q], refit, ml_cfg, explain=True)
            for model, v in out.items():
                preds.append(meta.loc[q].assign(model=model, forecast=v))
            if contrib is None:
                key = f"{s}: no events in training rows, ml_lgbm = trailing rate"
                notes[key] = notes.get(key, 0) + int(q.sum())
                continue
            g = explain_groups(contrib).abs()
            imps.append(g.assign(series=s, grain=meta.loc[q, "grain"].to_numpy()))
    errors = pd.concat(preds, ignore_index=True) if preds else pd.DataFrame()
    if len(errors) and benchmarks:
        say("benchmarks")
        bm = _benchmarks((panel, _target_frame(target)), errors[errors["model"] == MODELS[0]],
                         origins_by_grain, score_until)
        keys = ["origin", "grain", "horizon", "series"]
        base = errors[errors["model"] == MODELS[0]].drop(columns=["model", "forecast"])
        errors = pd.concat([errors, base.merge(bm, on=keys)], ignore_index=True)
    if len(errors):
        errors["error"] = errors["forecast"] - errors["actual"]
        errors["model_version"] = f"{VERSION}_{ml_cfg.tag()}"
        errors = add_intervals(errors.drop(columns=["kind", "base", "same_source"]))
    importance = (pd.concat(imps).groupby(["series", "grain"]).mean().reset_index()
                  if imps else pd.DataFrame())
    return MLResult(errors, importance,
                    pd.DataFrame(sorted(notes.items()), columns=["note", "n_forecasts"]))


def summary(errors: pd.DataFrame) -> pd.DataFrame:
    """Herd-level scores per series x grain x horizon x model: n, accuracy (1 - WAPE),
    share within +-10 % (periods with a non-zero actual), bias %, skill against persistence
    on the same periods. Periods with zero events count in accuracy, bias and skill: most
    days and many weeks have no event, and dropping them would score only the busy ones."""
    if not len(errors):
        return pd.DataFrame()
    e = errors
    keys = ["series", "grain", "horizon"]
    pers = e[e["model"] == "persistence"].set_index(keys + ["origin"])["error"].abs()
    rows = []
    for k, g in e.groupby(keys + ["model"]):
        tot = g["actual"].sum()
        pos = g[g["actual"] > 0]
        ape = pos["error"].abs() / pos["actual"]
        row = dict(zip(keys + ["model"], k), n=len(g),
                   accuracy=1 - g["error"].abs().sum() / tot if tot > 0 else np.nan,
                   within_10=float((ape <= 0.10 + 1e-9).mean()) if len(pos) else np.nan,
                   bias_pct=g["error"].sum() / tot if tot > 0 else np.nan)
        idx = pd.MultiIndex.from_frame(g[keys + ["origin"]])
        p = pers.reindex(idx)
        both = p.notna().to_numpy()
        row["skill_vs_persistence"] = (1 - g["error"].abs().to_numpy()[both].mean() / p.to_numpy()[both].mean()
                                       if both.sum() and p.to_numpy()[both].mean() > 0 else np.nan)
        rows.append(row)
    return pd.DataFrame(rows)
