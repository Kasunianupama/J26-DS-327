"""Time-series hyperparameter search for the cow-yield residual models (notebook 05).

The search only ever sees the training block. It is split into expanding folds: fold *k*
trains on cow-days up to cut *k* and is scored on the cow-days between cut *k* and cut
*k+1* (one-day-ahead, walk-forward, the same features as the real models). Validation
and test cow-days are never touched, so model selection and the final test stay honest.

Search: seeded random sampling (reproducible, no extra dependency). Trial 0 is always the
current default setting, so the table shows directly whether tuning helped. The score is
WAPE in litres pooled over all folds; lower is better.
"""
from __future__ import annotations

import time
from datetime import date

import numpy as np
import pandas as pd

from .cow_accuracy import (BASE_FEATURES, LEVEL_FEATURES, TRAIN_START, CowSplit,
                           _add_level_features, _design, fit_wood_mixed,
                           prepare_accuracy_frame, prepare_cowdays, recalibrate)

FOLD_QUANTILES = (0.60, 0.70, 0.80, 0.90)

LGBM_DEFAULT = dict(objective="huber", n_estimators=350, learning_rate=0.03, num_leaves=15,
                    min_child_samples=40, subsample=0.8, subsample_freq=0,
                    colsample_bytree=0.8, reg_lambda=1.0)
RF_DEFAULT = dict(n_estimators=250, min_samples_leaf=20, max_features=0.8, max_depth=None,
                  max_samples=None)


def _sample_lgbm(rng: np.random.Generator) -> dict:
    return dict(
        objective=str(rng.choice(["huber", "l1", "l2"])),
        n_estimators=int(rng.choice([200, 400, 700, 1000, 1500])),
        learning_rate=float(np.exp(rng.uniform(np.log(0.01), np.log(0.1)))),
        num_leaves=int(rng.choice([7, 15, 31, 63, 127])),
        min_child_samples=int(rng.choice([10, 20, 40, 80, 160])),
        subsample=float(rng.uniform(0.5, 1.0)),
        subsample_freq=1,
        colsample_bytree=float(rng.uniform(0.4, 1.0)),
        reg_lambda=float(np.exp(rng.uniform(np.log(1e-3), np.log(10.0)))),
    )


def _sample_rf(rng: np.random.Generator) -> dict:
    return dict(
        n_estimators=200,
        min_samples_leaf=int(rng.choice([5, 10, 20, 40, 80])),
        max_features=float(rng.choice([0.3, 0.5, 0.7, 0.9])),
        max_depth=[None, 12, 20, 30][int(rng.integers(4))],
        max_samples=float(rng.choice([0.3, 0.5, 0.7])),
    )


def _fold_cuts(raw: pd.DataFrame, train_end: date) -> list[pd.Timestamp]:
    d = pd.to_datetime(raw["date"])
    d = d[d <= pd.Timestamp(train_end)].sort_values()
    cuts = [d.iloc[int(q * (len(d) - 1))].normalize() for q in FOLD_QUANTILES]
    return sorted(set(cuts)) + [pd.Timestamp(train_end)]


def build_folds(raw: pd.DataFrame, train_end: date, events: dict | None = None,
                min_source_records: int = 100, verbose: bool = False) -> list[dict]:
    """Prepare each expanding fold once: frame, Wood curve, design matrix, scoring rows."""
    raw = raw[pd.to_datetime(raw["date"]) <= pd.Timestamp(train_end)]
    cuts = _fold_cuts(raw, train_end)
    folds = []
    for k in range(len(cuts) - 1):
        t0 = time.perf_counter()
        fit_end, score_end = cuts[k].date(), cuts[k + 1].date()
        f = prepare_accuracy_frame(raw, train_end=fit_end, validation_end=score_end,
                                   evaluation_mode="walk_forward", events=events,
                                   min_source_records=min_source_records)
        features = (BASE_FEATURES + tuple(f.attrs.get("event_features", ()))
                    + LEVEL_FEATURES)
        split = CowSplit(start=TRAIN_START, train_end=fit_end, validate_end=score_end,
                         gap_end=score_end, recal_end=score_end)
        fitting = prepare_cowdays(f, split)
        wood = fit_wood_mixed(fitting, calendar_level=True).predict(fitting)
        f = _add_level_features(f, wood)
        x = _design(f, features)
        train = (f["period"] == "train").to_numpy()
        score = ((f["period"] == "validation") & f["score_eligible"]).to_numpy()
        folds.append({"fold": k + 1, "fit_end": fit_end, "score_end": score_end, "x": x,
                      "train": train, "score": score, "wood": wood,
                      "y": f["litres"].to_numpy(),
                      "target": np.log(f["litres"].to_numpy() / np.maximum(wood, 1e-6)),
                      # for the torch models: walk-forward recalibrated base, week index
                      "recal_base": recalibrate(f, wood),
                      "weeks": ((f["date"] - f["date"].min()).dt.days // 7).to_numpy()})
        if verbose:
            print(f"[cow-tuning] fold {k + 1}: train to {fit_end} ({int(train.sum()):,} rows), "
                  f"score to {score_end} ({int(score.sum()):,} rows), "
                  f"prepared in {time.perf_counter() - t0:,.1f}s")
    return folds


def _make_model(kind: str, params: dict, n_jobs: int, seed: int):
    from lightgbm import LGBMRegressor
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import make_pipeline

    if kind == "lgbm":
        return LGBMRegressor(**params, random_state=seed, deterministic=True,
                             force_row_wise=True, n_jobs=n_jobs, verbose=-1)
    return make_pipeline(SimpleImputer(strategy="median", add_indicator=True),
                         RandomForestRegressor(**params, random_state=seed, n_jobs=n_jobs))


def tune_residual_model(folds: list[dict], kind: str = "lgbm", n_trials: int = 30,
                        seed: int = 17, n_jobs: int = -1,
                        verbose: bool = False) -> tuple[dict, pd.DataFrame]:
    """Random search over ``kind`` ("lgbm" or "rf"); returns best params and trial table."""
    if kind not in {"lgbm", "rf"}:
        raise ValueError("kind must be lgbm or rf")
    rng = np.random.default_rng(seed)
    sample = _sample_lgbm if kind == "lgbm" else _sample_rf
    default = LGBM_DEFAULT if kind == "lgbm" else RF_DEFAULT
    rows = []
    for trial in range(n_trials):
        params = dict(default) if trial == 0 else sample(rng)
        t0 = time.perf_counter()
        abs_err = total = 0.0
        fold_wape = []
        for fold in folds:
            if not fold["score"].any():
                continue
            model = _make_model(kind, params, n_jobs, seed)
            model.fit(fold["x"].loc[fold["train"]], fold["target"][fold["train"]])
            idx = fold["score"]
            pred = fold["wood"][idx] * np.exp(np.clip(model.predict(fold["x"].loc[idx]),
                                                      -0.7, 0.7))
            e, t = float(np.abs(pred - fold["y"][idx]).sum()), float(fold["y"][idx].sum())
            abs_err += e
            total += t
            fold_wape.append(100 * e / t)
        wape = 100 * abs_err / total if total else np.nan
        rows.append({"trial": trial, "setting": "default" if trial == 0 else "random",
                     "cv_wape_pct": wape, "cv_accuracy_pct": 100 - wape,
                     "fold_wape_pct": ", ".join(f"{w:.1f}" for w in fold_wape),
                     "seconds": round(time.perf_counter() - t0, 1), **params})
        if verbose:
            print(f"[cow-tuning] {kind} trial {trial:>2} ({rows[-1]['setting']}): "
                  f"CV accuracy {100 - wape:.2f}% in {rows[-1]['seconds']:.1f}s")
    table = pd.DataFrame(rows).sort_values("cv_wape_pct").reset_index(drop=True)
    best = table.iloc[0]
    best_params = {k: (None if isinstance(best[k], float) and np.isnan(best[k]) else best[k])
                   for k in default}
    for k, v in best_params.items():  # numpy scalars -> plain python for the estimators
        if isinstance(v, (np.integer,)):
            best_params[k] = int(v)
        elif isinstance(v, (np.floating,)):
            best_params[k] = float(v)
    if kind == "rf" and best_params.get("max_depth") is not None:
        best_params["max_depth"] = int(best_params["max_depth"])
    return best_params, table
