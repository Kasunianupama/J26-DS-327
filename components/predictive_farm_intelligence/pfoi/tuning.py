"""Nested, leak-free hyperparameter tuning for the stability gate and the Track A switch (G1/G2).

For every outer fold year Y (2019-2023) everything is chosen on the **inner** data only, i.e. labels
whose period ended by 1 January Y:

* inner split, chronological about 80:20 by forecast date: validation = inner forecast dates in the
  last 20 % of the inner span; training = inner labels whose period ended at least the grain's
  longest horizon before validation starts (embargo: daily 14 days, weekly 91 days, monthly 365
  days), so no training label is close to or overlaps a validation label;
* every setting in the grid is fitted on inner training and scored on inner validation (gate: Brier
  score; Track A: mean share within +-10 % over Track A cells); the best one is refitted on all inner
  data and used, unchanged, for the forecasts issued in Y;
* if inner validation has fewer than ``MIN_VAL_MISS`` misses the G1 default is kept.

The outer year is never seen during selection, so the outer scores are honest; the gap between the
best setting in hindsight and the nested choice is the optimism of tuning on the same data.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .gate import FOLD_YEARS, KEYS, LGBM_DEFAULT, LOGISTIC_DEFAULT, MISS_TOL, _auc_within, fit_predict_gate
from .specialists import TRACK_A_CELLS, fast_relevel

GAPS = {"daily": 14, "weekly": 91, "monthly": 365}
VAL_SHARE = 0.2
MIN_VAL_MISS = 5
DEFAULT_SPEC = ("logistic", tuple(sorted(LOGISTIC_DEFAULT.items())))


def gate_grid() -> list[tuple[str, tuple]]:
    """Gate settings: logistic strength of pull to zero, LightGBM depth / size / rate / leaf size.
    The G1 defaults come first, so ties keep them."""
    grid = [DEFAULT_SPEC, ("lgbm", tuple(sorted(LGBM_DEFAULT.items())))]
    grid += [("logistic", (("C", c),)) for c in (0.02, 0.1, 2.0)]
    for leaves, depth in ((2, 1), (4, 2), (8, 3)):
        for n in (50, 150, 400):
            for mcs in (20, 50):
                spec = ("lgbm", tuple(sorted({**LGBM_DEFAULT, "num_leaves": leaves, "max_depth": depth,
                                              "n_estimators": n, "min_child_samples": mcs}.items())))
                if spec not in grid:
                    grid.append(spec)
    return grid


def spec_label(spec) -> str:
    kind, params = spec
    short = {"C": "C", "num_leaves": "leaves", "max_depth": "depth", "n_estimators": "trees",
             "min_child_samples": "minleaf"}
    return kind + "(" + ",".join(f"{short[k]}={v}" for k, v in params if k in short) + ")"


def inner_split(labels: pd.DataFrame, year: int, val_share: float = VAL_SHARE, gaps=GAPS):
    """Masks (inner_all, inner_train, inner_val) and the validation start for fold year ``year``."""
    cut = pd.Timestamp(year, 1, 1)
    ends = pd.to_datetime(labels["period_end"])
    origins = pd.to_datetime(labels["origin"])
    inner = (ends <= cut).to_numpy()
    if not inner.any():
        return inner, inner, inner, None
    o0 = origins[inner].min()
    val_start = cut - (cut - o0) * val_share
    val = inner & (origins >= val_start).to_numpy()
    gap = labels["grain"].map(gaps).fillna(max(gaps.values())).to_numpy()
    train = inner & (ends + pd.to_timedelta(gap, unit="D") <= val_start).to_numpy()
    return inner, train, val, val_start


def _brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


@dataclass
class TunedGate:
    predictions: pd.DataFrame     # outer rows: KEYS, period_end, miss, forecast, actual, fold_year, p_base_rate, p_tuned
    folds: pd.DataFrame           # year, sizes, validation start, chosen setting, validation Brier
    grid_scores: pd.DataFrame     # year x setting: validation Brier
    validation: dict              # year -> inner validation rows with the chosen gate's p


def tuned_gate(labels: pd.DataFrame, X: pd.DataFrame, fold_years=FOLD_YEARS, seed: int = 17) -> TunedGate:
    from .gate import base_rate_fn

    grid = gate_grid()
    preds, folds, scores, validation = [], [], [], {}
    origins = pd.to_datetime(labels["origin"])
    for year in fold_years:
        inner, tr, va, vstart = inner_split(labels, year)
        te = ((origins >= pd.Timestamp(year, 1, 1)) & (origins < pd.Timestamp(year + 1, 1, 1))).to_numpy()
        if not te.any() or not inner.any():
            continue
        ytr, yva = labels.loc[tr, "miss"].to_numpy(), labels.loc[va, "miss"].to_numpy()
        usable = (tr.sum() >= 100 and 10 <= ytr.sum() <= tr.sum() - 10 and yva.sum() >= MIN_VAL_MISS
                  and va.sum() - yva.sum() >= MIN_VAL_MISS)
        best, best_score, val_p = DEFAULT_SPEC, np.nan, None
        if usable:
            ref = _brier(yva, base_rate_fn(labels.loc[tr])(labels.loc[va]))
            for spec in grid:
                p = fit_predict_gate(spec[0], dict(spec[1]), labels.loc[tr], X.loc[tr],
                                     labels.loc[va], X.loc[va], seed)
                b = _brier(yva, p)
                scores.append(dict(fold_year=year, setting=spec_label(spec), val_brier=b,
                                   val_brier_skill=1 - b / ref if ref > 0 else np.nan))
                if not np.isfinite(best_score) or b < best_score - 1e-12:
                    best, best_score, val_p = spec, b, p
        if val_p is None and va.any():
            val_p = fit_predict_gate(best[0], dict(best[1]), labels.loc[tr], X.loc[tr], labels.loc[va], X.loc[va], seed) \
                if tr.sum() >= 100 and 0 < ytr.sum() < tr.sum() else np.full(int(va.sum()), np.nan)
        validation[year] = labels.loc[va, KEYS + ["miss", "forecast", "actual"]].assign(p=val_p)
        default_score = next((r["val_brier"] for r in scores
                              if r["fold_year"] == year and r["setting"] == spec_label(DEFAULT_SPEC)), np.nan)
        folds.append(dict(fold_year=year, n_inner_train=int(tr.sum()), n_inner_val=int(va.sum()),
                          val_misses=int(yva.sum()), val_start=vstart.date() if vstart is not None else None,
                          tuned=bool(usable), chosen=spec_label(best), val_brier_chosen=best_score,
                          val_brier_default=default_score))
        out = labels.loc[te, KEYS + ["period_end", "miss", "forecast", "actual"]].copy()
        out["fold_year"] = year
        out["p_base_rate"] = base_rate_fn(labels.loc[inner])(out)
        out["p_tuned"] = fit_predict_gate(best[0], dict(best[1]), labels.loc[inner], X.loc[inner],
                                          labels.loc[te], X.loc[te], seed)
        out["setting"] = spec_label(best)
        preds.append(out)
    return TunedGate(predictions=pd.concat(preds, ignore_index=True) if preds else pd.DataFrame(),
                     folds=pd.DataFrame(folds), grid_scores=pd.DataFrame(scores), validation=validation)


def tuned_gate_scores(pred: pd.DataFrame, fixed: pd.DataFrame | None = None) -> pd.DataFrame:
    """Outer scores of the tuned gate (and, if given, the G1 fixed gates on the same rows)."""
    if not len(pred):
        return pd.DataFrame()
    cols = {"tuned": "p_tuned"}
    df = pred.copy()
    if fixed is not None and len(fixed):
        f = fixed[KEYS + ["p_logistic", "p_lgbm"]].copy()
        for c in ("origin", "period_start"):
            f[c] = pd.to_datetime(f[c]).dt.date
            df[c] = pd.to_datetime(df[c]).dt.date
        df = df.merge(f, on=KEYS, how="left")
        cols.update({"g1_logistic": "p_logistic", "g1_lgbm": "p_lgbm"})
    rows = []
    for key, g in [("all", df)] + list(df.groupby("fold_year")):
        y = g["miss"].to_numpy()
        ref = _brier(y, g["p_base_rate"].to_numpy())
        for name, c in cols.items():
            p = g[c].to_numpy(dtype=float)
            if not np.isfinite(p).all():
                continue
            b = _brier(y, p)
            rows.append(dict(fold_year=key, gate=name, n=len(g), n_miss=int(y.sum()), brier=b,
                             brier_skill=1 - b / ref if ref > 0 else np.nan, auc=_auc_within(g, c)))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- Track A switch

WINDOWS = (7, 14, 28)
THRESHOLDS = (0.3, 0.4, 0.5, 0.6, 0.7)
DEFAULT_A = (14, 0.5)


def _cell_mean_hit(rows: pd.DataFrame) -> float:
    r = rows[rows["actual"] > 0]
    if not len(r):
        return np.nan
    hit = (r["forecast"] - r["actual"]).abs() / r["actual"] <= MISS_TOL + 1e-9
    return float(hit.groupby([r["grain"], r["horizon"]]).mean().mean())


def _switched(rows: pd.DataFrame, s1: pd.Series, p: np.ndarray, threshold: float) -> pd.DataFrame:
    out = rows.copy()
    key = pd.MultiIndex.from_frame(out[KEYS])
    alt = s1.reindex(key).to_numpy(dtype=float)
    use = (p > threshold) & np.isfinite(alt)
    out.loc[use, "forecast"] = alt[use]
    out["switched"] = use
    return out


def tuned_track_a(raw: pd.DataFrame, gate: TunedGate, windows=WINDOWS, thresholds=THRESHOLDS):
    """Per fold year: S1 window and gate threshold chosen on the inner validation rows (Track A
    cells, the inner gate's probabilities); applied to the year's Track A forecasts. Returns
    (outer rows of base and tuned switch with ``switched``, choice table, grid table)."""
    cells = set(TRACK_A_CELLS)
    s1 = {}
    for w in windows:
        f = fast_relevel(raw, window_days=w)
        for c in ("origin", "period_start"):
            f[c] = pd.to_datetime(f[c]).dt.date
        s1[w] = f.drop_duplicates(KEYS).set_index(KEYS)["forecast"]
    in_a = lambda f: np.array([(g, int(h)) in cells for g, h in zip(f["grain"], f["horizon"])])  # noqa: E731
    outer, choice, grid_rows = [], [], []
    for year, val in gate.validation.items():
        v = val.copy()
        for c in ("origin", "period_start"):
            v[c] = pd.to_datetime(v[c]).dt.date
        v = v[in_a(v)]
        best, best_score = DEFAULT_A, -np.inf
        base_score = _cell_mean_hit(v) if len(v) else np.nan
        if len(v) and np.isfinite(v["p"]).all():
            for w in windows:
                for t in thresholds:
                    sc = _cell_mean_hit(_switched(v, s1[w], v["p"].to_numpy(), t))
                    grid_rows.append(dict(fold_year=year, window=w, threshold=t, val_hit=sc, val_hit_base=base_score))
                    if sc > best_score + 1e-12 or (abs(sc - best_score) <= 1e-12 and (w, t) == DEFAULT_A):
                        best, best_score = (w, t), sc
        choice.append(dict(fold_year=year, n_val=len(v), window=best[0], threshold=best[1],
                           val_hit_chosen=best_score if np.isfinite(best_score) else np.nan, val_hit_base=base_score))
        o = gate.predictions[gate.predictions["fold_year"] == year].copy()
        for c in ("origin", "period_start"):
            o[c] = pd.to_datetime(o[c]).dt.date
        p = np.where(in_a(o), o["p_tuned"].to_numpy(), 0.0)
        outer.append(_switched(o, s1[best[0]], p, best[1]))
    rows = pd.concat(outer, ignore_index=True) if outer else pd.DataFrame()
    return rows, pd.DataFrame(choice), pd.DataFrame(grid_rows)


# --------------------------------------------------------------------------- Track B settings

B_SETTINGS = tuple((mode, weeks, point) for mode in ("current", "all") for weeks in (520, 260, 104)
                   for point in ("median", "mean"))
B_DEFAULT = ("current", 520, "median")


def b_label(setting) -> str:
    return f"{setting[0]}/{setting[1]}w/{setting[2]}"


def tuned_track_b(base_trusted: pd.DataFrame, herd: pd.DataFrame, weekly: pd.DataFrame,
                  predictors: dict, fold_years=FOLD_YEARS, settings=B_SETTINGS):
    """Chronos-2 context and point settings chosen per fold year on inner validation (long cells,
    forecast dates in the last 20 % of the inner span, periods ended by 1 January Y; nothing is
    fitted, so no training embargo is needed). Returns (outer rows of the tuned candidate
    ``chronos2_tuned``, choice table, per-setting hindsight table)."""
    from .specialists import TRACK_B_CELLS, track_b_rows, weekly_path_forecasts

    base = base_trusted.copy()
    for c in ("origin", "period_start", "period_end"):
        base[c] = pd.to_datetime(base[c]).dt.date
    origins = sorted(set(base.loc[base["grain"].isin(["weekly", "monthly"]), "origin"]))
    rows = {}
    for st in settings:
        paths = weekly_path_forecasts(weekly, origins, "ypc", predictors[st[2]], max_weeks=st[1], mode=st[0])
        r = track_b_rows(base, herd, paths, {})
        rows[st] = r[r["model"] == "chronos2_ypc_x_engine"].drop_duplicates(KEYS).set_index(KEYS) if len(r) else None
    long = set(TRACK_B_CELLS)
    b = base[[(g, int(h)) in long for g, h in zip(base["grain"], base["horizon"])]].drop_duplicates(KEYS).set_index(KEYS)

    def hit_on(idx, st):
        r = rows[st]
        if r is None:
            return np.nan
        k = idx.intersection(r.index)
        if not len(k):
            return np.nan
        f = r.loc[k]
        return _cell_mean_hit(f.reset_index())

    out, choice = [], []
    o_all = pd.to_datetime(b.index.get_level_values("origin"))
    e_all = pd.to_datetime(b["period_end"])
    for year in fold_years:
        cut = pd.Timestamp(year, 1, 1)
        inner = (e_all <= cut).to_numpy()
        if not inner.any():
            continue
        vstart = cut - (cut - o_all[inner].min()) * VAL_SHARE
        val_idx = b.index[inner & (o_all >= vstart)]
        best, best_score = B_DEFAULT, -np.inf
        for st in settings:
            sc = hit_on(val_idx, st)
            if np.isfinite(sc) and (sc > best_score + 1e-12 or (abs(sc - best_score) <= 1e-12 and st == B_DEFAULT)):
                best, best_score = st, sc
        choice.append(dict(fold_year=year, n_val=len(val_idx), chosen=b_label(best),
                           val_hit_chosen=best_score if np.isfinite(best_score) else np.nan,
                           val_hit_default=hit_on(val_idx, B_DEFAULT)))
        r = rows[best]
        if r is None:
            continue
        yr = r[(pd.to_datetime(r.index.get_level_values("origin")) >= cut)
               & (pd.to_datetime(r.index.get_level_values("origin")) < pd.Timestamp(year + 1, 1, 1))]
        out.append(yr.reset_index().assign(model="chronos2_tuned", setting=b_label(best)))
    hindsight = []
    years_idx = b.index[(o_all >= pd.Timestamp(min(fold_years), 1, 1)) & (o_all < pd.Timestamp(max(fold_years) + 1, 1, 1))]
    for st in settings:
        hindsight.append(dict(setting=b_label(st), outer_mean_hit_long_cells=hit_on(years_idx, st)))
    return (pd.concat(out, ignore_index=True) if out else pd.DataFrame(), pd.DataFrame(choice),
            pd.DataFrame(hindsight))
