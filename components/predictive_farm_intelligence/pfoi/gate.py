"""Stability gate, step G1: can Farm X's unstable positions be recognised at the forecast date?

Design (user decision 2026-10-22): pfoi-1.2.0-dev stays the forecaster in stable conditions; a
gate judges at each forecast date whether the herd is in an unstable position, and only then a
specialist makes its own forecast. Persistence is never a specialist (benchmark only).

This step answers the go/no-go question before any specialist is built: do signals known at
the origin separate the forecasts that 1.2.0-dev later missed by more than 10 % from the ones
it got right? Everything works on saved backtest error tables plus herd-level daily aggregates.

* **Label** (training only): 1 if the base model's forecast was more than 10 % from the record
  (``hit_rate`` definition). Only trusted periods (band normal or degraded) are labels;
  unverified and gap periods never are. A label is used for fold year Y only if its period had
  ended before 1 January Y.
* **Features** (``GATE_FEATURES``), all from days before the origin: the base model's own
  recently finished errors (they arrive within days, unlike a 12-month error), litres per
  recorded milking cow on trusted days (change and volatility), trusted-day share and staleness,
  identified share, age of the current milk source, change in milking cows, age of the latest
  break found by ``breaks.detect_breaks`` (each break uses only days up to its date), and the
  **filtered** probability of the high-variance regime of a two-regime Markov-switching model of
  weekly yield-per-cow changes (smoothed probabilities would use later weeks: never used).
  Missing stays missing (NaN); nothing is filled with zero.
* **Gates**, refitted once per fold year on earlier labels only, fixed settings (no selection,
  so no selection optimism in this step): training miss rate per grain x horizon (no-skill
  reference), logistic regression (median fill + missing flags + scaling, all fitted inside the
  fold) and a shallow LightGBM classifier (NaN handled natively). Both learned gates start
  from the reference: LightGBM boosts from the logit of the cell's training miss rate
  (``init_score``), the logistic gate gets that logit as an input. They only have to explain
  why this origin is riskier or safer than usual for its horizon, which keeps a gate with no
  signal close to the reference instead of overconfident.
* **Switching check**: when the gate says unstable (p > threshold), use the non-persistence
  alternative that had the best hit rate on the base model's past misses (earlier labels only).
  This uses models that already exist, so it is a lower bound for what a purpose-built
  specialist must beat; the hindsight best-of ceiling is reported and labelled as such.

Outputs are herd-level aggregates (scores by fold year, grain and horizon). No animal data.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import warnings

import numpy as np
import pandas as pd

from .episodes import MAX_LITRES_PER_COW_DAY, VERIFIED_BANDS

MISS_TOL = 0.10
FOLD_YEARS = (2019, 2020, 2021, 2022, 2023)
EXCLUDED_ALTERNATIVES = ("persistence",)  # user decision 2026-10-22: never a specialist
KEYS = ["grain", "horizon", "origin", "period_start"]
GRAINS = ("daily", "weekly", "monthly")

GATE_FEATURES = (
    "horizon_days",
    "err_abs_6w", "err_signed_6w", "err_abs_prior", "err_jump", "n_err_6w",
    "ypc_change_28d", "ypc_abs_change_28d", "ypc_vol_28d",
    "trusted_share_28d", "trusted_share_90d", "days_since_trusted",
    "identified_share_28d", "source_age_days", "cows_change_90d", "break_age_days",
    "ms_unstable_prob",
)
ORIGIN_FEATURES = GATE_FEATURES[1:]  # everything except the horizon is a property of the origin

# Pre-registered go/no-go rule for G1 (fixed 2026-10-22, before any real-data run)
GO_MIN_AUC = 0.65
GO_MIN_YEARS = 3
# User target (2026-10-22): within-cell AUC about 0.80, especially at long horizons
AUC_TARGET = 0.80
LONG_CELLS = (("weekly", 13), ("monthly", 6), ("monthly", 12))


@dataclass(frozen=True)
class GateConfig:
    recent_days: int = 42          # "recent" finished errors: period ended in the last 6 weeks
    prior_days: int = 180          # comparison window before that
    markov: bool = True
    markov_min_weeks: int = 52
    min_train: int = 200           # training labels needed before a fold year is gated
    min_train_miss: int = 20
    threshold: float = 0.5
    seed: int = 17


# --------------------------------------------------------------------------- daily signals

def daily_signals(daily: pd.DataFrame) -> pd.DataFrame:
    """Calendar-day frame: trusted milk day, log litres per recorded milking cow (trusted days
    only), milking cows, identified share, milk source, herd size."""
    d = daily.copy()
    d.index = pd.to_datetime(d["date"])
    d = d.sort_index()
    d = d[~d.index.duplicated()]
    d = d.reindex(pd.date_range(d.index.min(), d.index.max()))
    col = lambda c: d[c] if c in d else pd.Series(np.nan, index=d.index)  # noqa: E731
    litres = pd.to_numeric(col("target_litres"), errors="coerce")
    cows = pd.to_numeric(col("milking"), errors="coerce")
    ok = col("is_scoreable").astype("boolean").fillna(False).astype(bool)
    gap = pd.to_numeric(col("data_gap"), errors="coerce").fillna(0) > 0
    ypc = (litres / cows).where((cows > 0) & (litres > 0))
    trusted = ok & ~gap & ypc.notna() & (ypc <= MAX_LITRES_PER_COW_DAY)
    out = pd.DataFrame(index=d.index)
    out["trusted"] = trusted
    out["log_ypc"] = np.log(ypc.where(trusted))
    out["milking"] = cows.where(cows > 0)
    out["ids"] = pd.to_numeric(col("identified_share"), errors="coerce")
    out["source"] = col("target_source").where(col("target_source").notna(), None)
    out["n_herd"] = pd.to_numeric(col("n_herd"), errors="coerce")
    return out


def _weekly_ypc_changes(sig: pd.DataFrame) -> pd.Series:
    """Week-to-week change of mean log yield per cow (weeks ending Sunday; trusted days only;
    weeks with fewer than 4 trusted days are missing and skipped)."""
    w = sig["log_ypc"].resample("W-SUN")
    mean, n = w.mean(), w.count()
    return mean.where(n >= 4).dropna().diff().dropna()


class MarkovSignal:
    """Filtered probability of the high-variance regime at the day before each origin.

    Parameters are refitted at each quarter start on weekly changes whose week ended before it;
    the filter then runs on weeks ended before the origin. Only the filtered probability (past
    and present weeks) is returned, never the smoothed one."""

    def __init__(self, sig: pd.DataFrame, min_weeks: int = 52):
        self.x = _weekly_ypc_changes(sig)
        self.min_weeks = min_weeks
        self._params: dict = {}

    def _fit(self, cutoff: pd.Timestamp):
        if cutoff not in self._params:
            from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression

            x = self.x[self.x.index < cutoff].to_numpy()
            p = None
            if len(x) >= self.min_weeks and np.std(x) > 0:
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        p = np.asarray(MarkovRegression(x, k_regimes=2, switching_variance=True)
                                       .fit(disp=False).params)
                except Exception:  # noqa: BLE001  (a failed fit is a missing feature)
                    p = None
            self._params[cutoff] = p
        return self._params[cutoff]

    def at(self, origin: date) -> float:
        from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression

        o = pd.Timestamp(origin)
        q = pd.Timestamp(year=o.year, month=3 * ((o.month - 1) // 3) + 1, day=1)
        p = self._fit(q)
        x = self.x[self.x.index < o].to_numpy()  # week ending Sunday < origin: ended before it
        if p is None or len(x) < self.min_weeks:
            return np.nan
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                f = MarkovRegression(x, k_regimes=2, switching_variance=True).filter(p)
            probs = np.asarray(f.filtered_marginal_probabilities)
        except Exception:  # noqa: BLE001
            return np.nan
        high = int(np.argmax(p[-2:]))  # sigma2[0], sigma2[1]
        return float(probs[-1, high])


# --------------------------------------------------------------------------- features

def label_rows(errors: pd.DataFrame, base_model: str, series: str = "herd_milk") -> pd.DataFrame:
    """Base-model rows usable as labels: positive forecast and record, trusted band when bands
    are present. Adds ``miss`` (outside +-10 %), ``log_err`` and ``horizon_days``."""
    r = errors[(errors["model"] == base_model)]
    if "series" in r:
        r = r[r["series"] == series]
    r = r[(r["actual"] > 0) & (r["forecast"] > 0)].copy()
    if "band" in r:
        r = r[r["band"].isin(VERIFIED_BANDS)]
    for c in ("origin", "period_start", "period_end"):
        r[c] = pd.to_datetime(r[c]).dt.date
    r["horizon"] = r["horizon"].astype(int)
    r["log_err"] = np.log(r["actual"] / r["forecast"])
    r["miss"] = ((r["forecast"] - r["actual"]).abs() / r["actual"] > MISS_TOL + 1e-9).astype(int)
    r["horizon_days"] = [(e - o).days for o, e in zip(r["origin"], r["period_end"])]
    return r.drop_duplicates(KEYS).reset_index(drop=True)


class GateFeatures:
    """Origin-level gate features from days and finished errors before the origin only."""

    def __init__(self, daily: pd.DataFrame, labels: pd.DataFrame, cfg: GateConfig = GateConfig(),
                 breaks: list[date] | None = None):
        self.cfg = cfg
        self.sig = daily_signals(daily)
        self.err_end = pd.to_datetime(labels["period_end"]).to_numpy()
        self.err_y = labels["log_err"].to_numpy(dtype=float)
        if breaks is None:
            from .breaks import detect_breaks

            frame = daily.copy()
            breaks = detect_breaks(frame) if "n_herd" in frame or "is_scoreable" in frame else []
        self.breaks = sorted(pd.Timestamp(b) for b in breaks)
        self.markov = MarkovSignal(self.sig, cfg.markov_min_weeks) if cfg.markov else None
        self._cache: dict = {}

    def _window(self, col: str, day: pd.Timestamp, days: int) -> pd.Series:
        return self.sig[col].loc[day - pd.Timedelta(days=days - 1):day]

    def row(self, origin: date) -> dict:
        if origin in self._cache:
            return self._cache[origin]
        o = pd.Timestamp(origin)
        day = o - pd.Timedelta(days=1)
        cfg = self.cfg
        out: dict = {}
        # the base model's own finished errors (period ended by the origin)
        done = self.err_end <= o.to_datetime64()
        age = (o.to_datetime64() - self.err_end) / np.timedelta64(1, "D")
        recent = done & (age < cfg.recent_days)
        prior = done & (age >= cfg.recent_days) & (age < cfg.prior_days)
        yr, yp = self.err_y[recent], self.err_y[prior]
        out["n_err_6w"] = float(recent.sum())
        out["err_abs_6w"] = float(np.abs(yr).mean()) if len(yr) else np.nan
        out["err_signed_6w"] = float(yr.mean()) if len(yr) else np.nan
        out["err_abs_prior"] = float(np.abs(yp).mean()) if len(yp) else np.nan
        out["err_jump"] = out["err_abs_6w"] - out["err_abs_prior"]
        # yield per recorded milking cow, trusted days only
        if day < self.sig.index[0]:
            for k in ORIGIN_FEATURES:
                out.setdefault(k, np.nan)
            self._cache[origin] = out
            return out
        lp = self.sig["log_ypc"]
        last = lp.loc[day - pd.Timedelta(days=27):day].dropna()
        before = lp.loc[day - pd.Timedelta(days=89):day - pd.Timedelta(days=28)].dropna()
        out["ypc_change_28d"] = float(last.mean() - before.mean()) if len(last) >= 7 and len(before) >= 14 else np.nan
        out["ypc_abs_change_28d"] = abs(out["ypc_change_28d"])
        out["ypc_vol_28d"] = float(last.diff().dropna().std()) if len(last) >= 10 else np.nan
        tr = self.sig["trusted"]
        out["trusted_share_28d"] = float(self._window("trusted", day, 28).mean())
        out["trusted_share_90d"] = float(self._window("trusted", day, 90).mean())
        past_ok = tr.loc[:day]
        last_ok = past_ok.index[past_ok.to_numpy()].max() if past_ok.any() else None
        out["days_since_trusted"] = float((day - last_ok).days) if last_ok is not None else np.nan
        ids = self._window("ids", day, 28).dropna()
        out["identified_share_28d"] = float(ids.mean()) if len(ids) else np.nan
        src = self.sig["source"].loc[:day].dropna()
        if len(src):
            cur = src.iloc[-1]
            other = src[src != cur]
            start = src.index[0] if not len(other) else src[src.index > other.index[-1]].index[0]
            out["source_age_days"] = float((day - start).days)
        else:
            out["source_age_days"] = np.nan
        cows = self.sig["milking"]
        now = cows.loc[day - pd.Timedelta(days=13):day].dropna()
        then = cows.loc[day - pd.Timedelta(days=103):day - pd.Timedelta(days=90)].dropna()
        out["cows_change_90d"] = float(np.log(now.mean() / then.mean())) if len(now) and len(then) else np.nan
        past = [b for b in self.breaks if b <= day]
        out["break_age_days"] = float((day - past[-1]).days) if past else np.nan
        out["ms_unstable_prob"] = self.markov.at(origin) if self.markov is not None else np.nan
        self._cache[origin] = out
        return out

    def matrix(self, rows: pd.DataFrame) -> pd.DataFrame:
        vals = [self.row(o) for o in rows["origin"]]
        X = pd.DataFrame(vals, index=rows.index)[list(ORIGIN_FEATURES)]
        X.insert(0, "horizon_days", rows["horizon_days"].astype(float).to_numpy())
        for g in GRAINS:
            X[f"grain_{g}"] = (rows["grain"] == g).astype(float).to_numpy()
        return X


# --------------------------------------------------------------------------- gates

LOGISTIC_DEFAULT = dict(C=0.5)
LGBM_DEFAULT = dict(n_estimators=150, learning_rate=0.05, num_leaves=4, max_depth=2,
                    min_child_samples=30, reg_lambda=10.0, colsample_bytree=0.8)


def _logistic(seed: int, C: float = LOGISTIC_DEFAULT["C"]):
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    return make_pipeline(SimpleImputer(strategy="median", add_indicator=True,
                                       keep_empty_features=True),
                         StandardScaler(), LogisticRegression(C=C, max_iter=2000, random_state=seed))


def _lgbm(seed: int, **params):
    from lightgbm import LGBMClassifier

    return LGBMClassifier(**{**LGBM_DEFAULT, **params}, subsample=1.0, random_state=seed,
                          n_jobs=1, verbose=-1)


GATE_MODELS = ("base_rate", "logistic", "lgbm")


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), 1e-3, 1 - 1e-3)
    return np.log(p / (1 - p))


def base_rate_fn(train: pd.DataFrame):
    """Training miss rate per grain x horizon (overall rate for unseen cells)."""
    rate = train.groupby(["grain", "horizon"])["miss"].mean()
    overall = float(train["miss"].mean())
    return lambda f: np.array([float(rate.get((g, h), overall)) for g, h in zip(f["grain"], f["horizon"])])


def fit_predict_gate(kind: str, params: dict, train: pd.DataFrame, Xtr: pd.DataFrame,
                     test: pd.DataFrame, Xte: pd.DataFrame, seed: int = 17) -> np.ndarray:
    """One gate (``logistic`` or ``lgbm`` with ``params``) fitted on ``train`` labels, starting from
    the training base rate, and its probabilities for ``test`` rows."""
    cell = base_rate_fn(train)
    z_tr, z_te = _logit(cell(train)), _logit(cell(test))
    y = train["miss"].to_numpy()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if kind == "logistic":
            m = _logistic(seed, **params).fit(np.column_stack([Xtr.to_numpy(dtype=float), z_tr]), y)
            return m.predict_proba(np.column_stack([Xte.to_numpy(dtype=float), z_te]))[:, 1]
        m = _lgbm(seed, **params).fit(Xtr, y, init_score=z_tr)
        return 1.0 / (1.0 + np.exp(-(z_te + m.predict(Xte, raw_score=True))))


def forward_gate(labels: pd.DataFrame, X: pd.DataFrame, cfg: GateConfig = GateConfig(),
                 fold_years=FOLD_YEARS) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Gate probabilities for the origins of each fold year Y, fitted on labels whose period
    ended before 1 January Y. Returns (predictions, fold table)."""
    preds, folds = [], []
    ends = pd.to_datetime(labels["period_end"])
    origins = pd.to_datetime(labels["origin"])
    for year in fold_years:
        cut, nxt = pd.Timestamp(year, 1, 1), pd.Timestamp(year + 1, 1, 1)
        tr = (ends <= cut).to_numpy()
        te = ((origins >= cut) & (origins < nxt)).to_numpy()
        n_tr, n_miss = int(tr.sum()), int(labels.loc[tr, "miss"].sum())
        fitted = n_tr >= cfg.min_train and cfg.min_train_miss <= n_miss <= n_tr - cfg.min_train_miss
        folds.append(dict(fold_year=year, n_train=n_tr, n_train_miss=n_miss, n_test=int(te.sum()),
                          last_train_period_end=ends[tr].max().date() if tr.any() else None,
                          gated=fitted))
        if not te.any() or not fitted:
            continue
        ytr = labels.loc[tr, "miss"].to_numpy()
        Xtr, Xte = X.loc[tr], X.loc[te]
        out = labels.loc[te, KEYS + ["period_end", "miss", "forecast", "actual"]].copy()
        out["fold_year"] = year
        # no-skill reference: training miss rate of the same grain x horizon
        rate = labels.loc[tr].groupby(["grain", "horizon"])["miss"].mean()
        overall = float(ytr.mean())
        cell = lambda f: np.array([float(rate.get((g, h), overall))  # noqa: E731
                                   for g, h in zip(f["grain"], f["horizon"])])
        p_tr, p_te = cell(labels.loc[tr]), cell(out)
        out["p_base_rate"] = p_te
        z_tr, z_te = _logit(p_tr), _logit(p_te)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            A_tr = np.column_stack([Xtr.to_numpy(dtype=float), z_tr])
            A_te = np.column_stack([Xte.to_numpy(dtype=float), z_te])
            lr = _logistic(cfg.seed).fit(A_tr, ytr)
            out["p_logistic"] = lr.predict_proba(A_te)[:, 1]
            gb = _lgbm(cfg.seed).fit(Xtr, ytr, init_score=z_tr)
            out["p_lgbm"] = 1.0 / (1.0 + np.exp(-(z_te + gb.predict(Xte, raw_score=True))))
        preds.append(out)
    pred = pd.concat(preds, ignore_index=True) if preds else pd.DataFrame()
    return pred, pd.DataFrame(folds)


def _auc(y: np.ndarray, p: np.ndarray) -> float:
    from sklearn.metrics import roc_auc_score

    ok = np.isfinite(p)
    y, p = y[ok], p[ok]
    return float(roc_auc_score(y, p)) if len(np.unique(y)) == 2 else np.nan


def _auc_within(g: pd.DataFrame, col: str) -> float:
    """AUC inside each grain x horizon cell, averaged with weights n. The horizon alone predicts
    misses (long horizons miss more), so a pooled AUC would credit a gate with skill it does not
    have; within a cell only the origin's state can separate misses from hits."""
    vals, ns = [], []
    for _, c in g.groupby(["grain", "horizon"]):
        a = _auc(c["miss"].to_numpy(), c[col].to_numpy(dtype=float))
        if np.isfinite(a):
            vals.append(a)
            ns.append(len(c))
    return float(np.average(vals, weights=ns)) if vals else np.nan


def gate_scores(pred: pd.DataFrame, by: tuple[str, ...] = ("fold_year",)) -> pd.DataFrame:
    """Per gate and group: n, misses, Brier score, Brier skill against the base rate (above 0 =
    better than knowing only how often each horizon misses), AUC within grain x horizon cells
    (0.5 = no skill) and the pooled AUC (inflated by the horizon effect; shown for reference)."""
    if not len(pred):
        return pd.DataFrame()
    rows = []
    groups = [((), pred)] + list(pred.groupby(list(by))) if by else [((), pred)]
    for key, g in groups:
        key = key if isinstance(key, tuple) else (key,)
        y = g["miss"].to_numpy()
        b_ref = float(np.mean((g["p_base_rate"].to_numpy() - y) ** 2))
        for m in GATE_MODELS:
            p = g[f"p_{m}"].to_numpy()
            brier = float(np.mean((p - y) ** 2))
            row = dict(zip(by, key)) if key else {k: "all" for k in by}
            row.update(gate=m, n=len(g), n_miss=int(y.sum()), brier=brier,
                       brier_skill=1 - brier / b_ref if b_ref > 0 else np.nan,
                       auc=_auc_within(g, f"p_{m}"), auc_pooled=_auc(y, p))
            rows.append(row)
    return pd.DataFrame(rows)


def feature_auc(labels: pd.DataFrame, X: pd.DataFrame, fold_years=FOLD_YEARS) -> pd.DataFrame:
    """Descriptive: AUC of each single feature against the later miss, within grain x horizon
    cells, per fold year and over all fold years (0.5 = no separation; below 0.5 = separates
    with the opposite sign). Thresholds are not chosen here, so this is not a forecast."""
    yr = pd.to_datetime(labels["origin"]).dt.year
    base = labels[["grain", "horizon", "miss"]]
    rows = []
    for f in X.columns:
        if f.startswith("grain_") or f == "horizon_days":
            continue
        g = base.assign(v=X[f].to_numpy(dtype=float))
        m = yr.isin(fold_years).to_numpy()
        row = dict(feature=f, n_known=int(np.isfinite(g["v"].to_numpy()[m]).sum()),
                   auc_all=_auc_within(g[m], "v"))
        for y in fold_years:
            row[f"auc_{y}"] = _auc_within(g[(yr == y).to_numpy()], "v")
        rows.append(row)
    return pd.DataFrame(rows)


def go_verdict(scores: pd.DataFrame) -> tuple[bool, pd.DataFrame]:
    """Pre-registered G1 rule: a learned gate (logistic or LightGBM) must, over fold years
    2019-2023, have Brier skill above 0 and within-cell AUC of at least 0.65 overall, and Brier
    skill above 0 in at least 3 of the fold years it gated."""
    rows = []
    for m in ("logistic", "lgbm"):
        s = scores[scores["gate"] == m]
        overall = s[s["fold_year"] == "all"]
        years = s[s["fold_year"] != "all"]
        ok_all = bool(len(overall) and overall["brier_skill"].iloc[0] > 0 and overall["auc"].iloc[0] >= GO_MIN_AUC)
        n_good = int((years["brier_skill"] > 0).sum())
        rows.append(dict(gate=m, overall_brier_skill=overall["brier_skill"].iloc[0] if len(overall) else np.nan,
                         overall_auc=overall["auc"].iloc[0] if len(overall) else np.nan,
                         years_with_skill=n_good, years_gated=len(years),
                         passes=ok_all and n_good >= GO_MIN_YEARS))
    table = pd.DataFrame(rows)
    return bool(table["passes"].any()), table


def auc_target_table(pred: pd.DataFrame, gates=("logistic", "lgbm"), target: float = AUC_TARGET,
                     n_boot: int = 500, seed: int = 17) -> pd.DataFrame:
    """Per gate x grain x horizon over all fold years: n, misses, AUC, a 5-95 % interval from a
    bootstrap that resamples whole origin months (forecasts issued in the same month are
    dependent), whether the AUC reaches the target, and whether even the interval's lower end
    does. Long-horizon cells (``LONG_CELLS``) are flagged; they carry the user's target."""
    rng = np.random.default_rng(seed)
    rows = []
    for (gr, h), c in pred.groupby(["grain", "horizon"]):
        y = c["miss"].to_numpy()
        block = pd.to_datetime(c["origin"]).dt.to_period("M").to_numpy()
        ids = np.unique(block)
        members = [np.flatnonzero(block == b) for b in ids]
        for g in gates:
            p = c[f"p_{g}"].to_numpy(dtype=float)
            auc = _auc(y, p)
            boot = []
            if np.isfinite(auc):
                for _ in range(n_boot):
                    k = np.concatenate([members[i] for i in rng.integers(0, len(ids), len(ids))])
                    v = _auc(y[k], p[k])
                    if np.isfinite(v):
                        boot.append(v)
            lo, hi = (np.percentile(boot, [5, 95]) if len(boot) >= 50 else (np.nan, np.nan))
            rows.append(dict(gate=g, grain=gr, horizon=int(h), long=(gr, int(h)) in LONG_CELLS,
                             n=len(c), n_miss=int(y.sum()), n_months=len(ids), auc=auc,
                             auc_lo=float(lo), auc_hi=float(hi),
                             reaches_target=bool(np.isfinite(auc) and auc >= target),
                             lower_end_reaches=bool(np.isfinite(lo) and lo >= target)))
    order = {g: i for i, g in enumerate(GRAINS)}
    t = pd.DataFrame(rows)
    if not len(t):
        return t
    return t.sort_values(["gate", "grain", "horizon"], key=lambda s: s.map(order) if s.name == "grain" else s) \
        .reset_index(drop=True)


# --------------------------------------------------------------------------- switching check

def switch_check(pred: pd.DataFrame, labels: pd.DataFrame, alternatives: dict[str, pd.DataFrame],
                 gate: str = "lgbm", threshold: float = 0.5) -> pd.DataFrame:
    """Hit rate (+-10 %) per grain x horizon of: the base model; the gated switch (when the gate
    says unstable, the alternative with the best hit rate on the base model's misses among labels
    finished before the fold year); and the hindsight best-of ceiling (labelled, not a forecast).
    Persistence is refused as an alternative."""
    bad = [a for a in alternatives if a in EXCLUDED_ALTERNATIVES]
    if bad:
        raise ValueError(f"not allowed as a specialist: {bad}")
    if not len(pred) or not alternatives:
        return pd.DataFrame()

    def keyed(f: pd.DataFrame) -> pd.DataFrame:
        g = f.copy()
        for c in ("origin", "period_start"):
            g[c] = pd.to_datetime(g[c]).dt.date
        g["horizon"] = g["horizon"].astype(int)
        return g.drop_duplicates(KEYS).set_index(KEYS)

    alt = {a: keyed(f)["forecast"] for a, f in alternatives.items()}
    lab = labels.set_index(KEYS)
    lab_end = pd.to_datetime(lab["period_end"])
    rows = []
    out = pred.copy().set_index(KEYS)
    out["switched"] = out["forecast"]
    out["chosen"] = "base"
    for year, g in out.groupby("fold_year"):
        past_miss = lab[(lab_end <= pd.Timestamp(year, 1, 1)) & (lab["miss"] == 1)]
        best, best_hit = None, -1.0
        for a, f in alt.items():
            common = past_miss.index.intersection(f.index)
            if len(common) < 12:
                continue
            hit = float(((f.loc[common] - past_miss.loc[common, "actual"]).abs()
                         / past_miss.loc[common, "actual"] <= MISS_TOL + 1e-9).mean())
            if hit > best_hit:
                best, best_hit = a, hit
        if best is None:
            continue
        flag = g[f"p_{gate}"] > threshold
        idx = g.index[flag.to_numpy()].intersection(alt[best].index)
        out.loc[idx, "switched"] = alt[best].loc[idx].to_numpy()
        out.loc[idx, "chosen"] = best
    within = lambda f, a: (f - a).abs() / a <= MISS_TOL + 1e-9  # noqa: E731
    out["hit_base"] = within(out["forecast"], out["actual"])
    out["hit_switch"] = within(out["switched"], out["actual"])
    best_any = out["hit_base"].copy()
    for f in alt.values():
        common = out.index.intersection(f.index)
        best_any.loc[common] = best_any.loc[common].to_numpy() | within(
            f.loc[common], out.loc[common, "actual"]).to_numpy()
    out["hit_ceiling"] = best_any
    out = out.reset_index()
    for (gr, h), g in out.groupby(["grain", "horizon"]):
        rows.append(dict(grain=gr, horizon=int(h), n=len(g), share_switched=float((g["chosen"] != "base").mean()),
                         hit_base=float(g["hit_base"].mean()), hit_switch=float(g["hit_switch"].mean()),
                         hit_ceiling_hindsight=float(g["hit_ceiling"].mean())))
    order = {g: i for i, g in enumerate(GRAINS)}
    t = pd.DataFrame(rows)
    return t.sort_values(["grain", "horizon"], key=lambda s: s.map(order) if s.name == "grain" else s) \
        .reset_index(drop=True)


@dataclass
class GateAudit:
    folds: pd.DataFrame
    scores_by_year: pd.DataFrame
    scores_by_cell: pd.DataFrame
    features: pd.DataFrame
    auc_target: pd.DataFrame
    verdict: pd.DataFrame
    go: bool
    switch: pd.DataFrame
    predictions: pd.DataFrame


def run_gate_audit(errors: pd.DataFrame, daily: pd.DataFrame, base_model: str,
                   alternatives: tuple[str, ...] = (), cfg: GateConfig = GateConfig(),
                   fold_years=FOLD_YEARS, breaks: list[date] | None = None) -> GateAudit:
    labels = label_rows(errors, base_model)
    feats = GateFeatures(daily, labels, cfg, breaks=breaks)
    X = feats.matrix(labels)
    pred, folds = forward_gate(labels, X, cfg, fold_years)
    by_year = gate_scores(pred, ("fold_year",))
    by_cell = gate_scores(pred, ("grain", "horizon"))
    go, verdict = go_verdict(by_year) if len(by_year) else (False, pd.DataFrame())
    alts = {}
    for a in alternatives:
        f = errors[errors["model"] == a]
        if "series" in f:
            f = f[f["series"] == "herd_milk"]
        if len(f):
            alts[a] = f
    sw = switch_check(pred, labels, alts, threshold=cfg.threshold) if alts else pd.DataFrame()
    return GateAudit(folds=folds, scores_by_year=by_year, scores_by_cell=by_cell,
                     features=feature_auc(labels, X, fold_years),
                     auc_target=auc_target_table(pred) if len(pred) else pd.DataFrame(),
                     verdict=verdict, go=go,
                     switch=sw, predictions=pred)
