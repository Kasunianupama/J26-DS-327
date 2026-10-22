"""Layer 2: cow-level lactation model, summed to the whole milking herd (experimental).

The daily milk record is a small, shifting sample of the milking cows, so the herd mean of
recorded cows mixes yield with *which* cows were measured. Layer 2 models one cow-day:

    ln litres = curve(parity, DIM) + pregnancy effect + cow effect + noise

and predicts every milking cow, recorded or not, so herd litres = sum over all cows.
No lagged yield is used, so predictions run straight across recording gaps.

Two glass-box models share the same inputs, cow effect and retransformation:

* ``wood``: Wood curve per parity as a linear mixed model in log space
  (ln a_p + b_p ln d - c_p d, random intercept per cow, linear drop per day pregnant
  beyond 150 days). Every parameter is readable.
* ``ebm``: Explainable Boosting Machine on ln litres (DIM, parity, days pregnant, plus
  optional extra columns); each term is a plotted shape. The cow effect is the
  empirical-Bayes shrunken mean residual per cow.

Predictions: known cow = exp(eta + u_i) * smear_known; unknown cow (no training
record) = exp(eta) * smear_marginal, with Duan smearing factors from training residuals.

Calendar level (default on): one level per half-year of the training period, fitted next
to the curve so that the herd's yield drift does not leak into the curve or parity
effects. Dates after training use the last training half-year (the reference, effect 0);
the level is then followed by a trailing factor (``trailing_level``): actual / predicted
litres of the recorded cows over the previous 56 days, before the day itself (Layer 5 seed).

Date split (``CowSplit``), set from the user's monthly aggregates of 2026-10-22:
excluded < 2016-01, train 2016-01 .. 2020-12, validate 2021-01 .. 2022-04, gap
2022-05 .. 2026-03 (fragments and placeholder-only days, never fitted or scored),
recalibrate 2026-04 .. 2026-05 (recording ramps up), test from 2026-06 (scored once,
only when asked). Models are fitted on train rows only (guarded).

Outputs are aggregates only: scores, parameters and shape tables, never cow rows.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

PERIODS = ("excluded", "train", "validate", "gap", "recalibrate", "test")
PARITIES = ("1", "2", "3+")
DIM_RANGE = (5, 400)
MAX_LITRES = 18.0
PREG_REF_DAYS = 150
MIN_RECORDED_COWS = 20
TRAILING_DAYS = 56
MIN_TRAILING_COW_DAYS = 200


@dataclass(frozen=True)
class CowSplit:
    start: date = date(2016, 1, 1)
    train_end: date = date(2020, 12, 31)
    validate_end: date = date(2022, 4, 30)
    gap_end: date = date(2026, 3, 31)
    recal_end: date = date(2026, 5, 31)


DEFAULT_SPLIT = CowSplit()


def label_period(dates, split: CowSplit = DEFAULT_SPLIT) -> np.ndarray:
    d = pd.to_datetime(pd.Series(dates)).to_numpy()
    edges = [split.start, split.train_end, split.validate_end, split.gap_end, split.recal_end]
    ts = [np.datetime64(pd.Timestamp(e)) for e in edges]
    out = np.full(len(d), "test", dtype=object)
    out[d <= ts[4]] = "recalibrate"
    out[d <= ts[3]] = "gap"
    out[d <= ts[2]] = "validate"
    out[d <= ts[1]] = "train"
    out[d < ts[0]] = "excluded"
    return out


def half_year(dates) -> np.ndarray:
    d = pd.to_datetime(pd.Series(dates))
    return (d.dt.year.astype(str) + np.where(d.dt.month <= 6, "H1", "H2")).to_numpy()


def level_label(dates, split: CowSplit = DEFAULT_SPLIT) -> np.ndarray:
    """Calendar level of each date: its half-year, clipped to the training half-years."""
    d = pd.to_datetime(pd.Series(dates)).clip(lower=pd.Timestamp(split.start),
                                                upper=pd.Timestamp(split.train_end))
    return half_year(d)


def reference_level(split: CowSplit = DEFAULT_SPLIT) -> str:
    return str(half_year([split.train_end])[0])


def prepare_cowdays(frame: pd.DataFrame, split: CowSplit = DEFAULT_SPLIT) -> pd.DataFrame:
    """Add ``period`` and ``usable`` (a valid record that may be fitted or scored).

    ``frame``: one row per milking cow-day with date, animal, parity_group, dim,
    days_pregnant and litres (NaN when the cow has no record that day). Optional
    ``after_dry_off`` (record dated after the lactation's recorded dry-off, so DIM is not
    trustworthy) is never usable and gets ``dim_known`` False. Optional ``is_placeholder``
    rows (herd-total records, not a cow) are dropped. Cow-days that appear more than once
    are never usable; their count is in ``attrs``.
    """
    f = frame.copy()
    if "is_placeholder" in f:
        f = f[~f["is_placeholder"].astype("boolean").fillna(False).astype(bool)].copy()
    f["date"] = pd.to_datetime(f["date"])
    f["parity_group"] = f["parity_group"].astype(str)
    f["days_pregnant"] = f["days_pregnant"].fillna(0).clip(lower=0)
    f["period"] = label_period(f["date"], split)
    f["level"] = level_label(f["date"], split)
    f.attrs["reference_level"] = reference_level(split)
    dup = f.duplicated(["animal", "date"], keep=False)
    after = (f["after_dry_off"].astype("boolean").fillna(False).astype(bool) if "after_dry_off" in f
             else pd.Series(False, index=f.index))
    y = f["litres"]
    f["usable"] = (y.notna() & (y > 0) & (y <= MAX_LITRES)
                   & f["dim"].between(*DIM_RANGE)
                   & f["parity_group"].isin(PARITIES)
                   & ~f["period"].isin(["excluded", "gap"])
                   & ~dup & ~after)
    f["dim_known"] = f["dim"].notna() & (f["dim"] >= 1) & ~after
    f.attrs["duplicate_cow_day_rows"] = int(dup.sum())
    return f


def _train_rows(f: pd.DataFrame) -> pd.DataFrame:
    t = f[f["usable"] & (f["period"] == "train")]
    if t.empty:
        raise ValueError("no usable train cow-days")
    assert (t["period"] == "train").all()  # leakage guard: nothing after train_end
    return t


def shrunken_cow_effects(resid: np.ndarray, animals: np.ndarray) -> tuple[pd.Series, float, float]:
    """Empirical-Bayes cow effects (method of moments): u_i = n_i s2u / (n_i s2u + s2e) * mean_i."""
    g = pd.DataFrame({"r": resid, "a": animals}).groupby("a")["r"]
    n, m = g.size(), g.mean()
    within = g.var(ddof=1).fillna(0.0)
    df = (n - 1).clip(lower=0)
    s2e = float((within * df).sum() / max(df.sum(), 1))
    s2u = max(float(m.var(ddof=1) - (s2e / n).mean()), 0.0) if len(m) > 1 else 0.0
    w = n * s2u / (n * s2u + s2e) if s2e > 0 else pd.Series(1.0, index=n.index)
    return (w * m).rename("u"), s2u, s2e


@dataclass
class CowModel:
    """Shared prediction rule for both Layer 2 models."""

    name: str
    cow_effect: pd.Series
    smear_known: float
    smear_marginal: float
    sigma2_cow: float
    sigma2_resid: float

    def linear(self, f: pd.DataFrame) -> np.ndarray:
        raise NotImplementedError

    def predict(self, frame: pd.DataFrame, use_cow_effect: bool = True) -> np.ndarray:
        eta = self.linear(frame)
        if not use_cow_effect:
            return np.exp(eta) * self.smear_marginal
        u = frame["animal"].map(self.cow_effect)
        known = u.notna().to_numpy()
        return np.where(known, np.exp(eta + u.fillna(0.0).to_numpy()) * self.smear_known,
                        np.exp(eta) * self.smear_marginal)

    def _set_smearing(self, t: pd.DataFrame) -> None:
        eta = self.linear(t)
        u = t["animal"].map(self.cow_effect).fillna(0.0).to_numpy()
        e = np.log(t["litres"].to_numpy()) - eta
        self.smear_known = float(np.mean(np.exp(e - u)))
        self.smear_marginal = float(np.mean(np.exp(e)))


def _wood_design(f: pd.DataFrame, levels: tuple[str, ...] = ()) -> pd.DataFrame:
    d = np.maximum(f["dim"].to_numpy(dtype=float), 1.0)
    cols = {}
    for p in PARITIES:
        on = (f["parity_group"].to_numpy() == p).astype(float)
        cols[f"ln_a[{p}]"] = on
        cols[f"b[{p}]"] = on * np.log(d)
        cols[f"neg_c[{p}]"] = on * d
    cols["preg_late"] = np.maximum(f["days_pregnant"].to_numpy(dtype=float) - PREG_REF_DAYS, 0.0)
    for lv in levels:
        cols[f"level[{lv}]"] = (f["level"].to_numpy() == lv).astype(float)
    return pd.DataFrame(cols, index=f.index)


@dataclass
class WoodMixed(CowModel):
    params: pd.Series = field(default_factory=pd.Series)
    levels: tuple[str, ...] = ()  # fitted calendar levels, reference excluded
    reference: str = ""

    def linear(self, f: pd.DataFrame) -> np.ndarray:
        X = _wood_design(f, self.levels)
        return X.to_numpy() @ self.params.reindex(X.columns).fillna(0.0).to_numpy()

    def level_table(self) -> pd.DataFrame:
        """Calendar level per training half-year, relative to the reference (last) one."""
        rows = [{"level": lv, "log_effect": float(self.params.get(f"level[{lv}]", 0.0))}
                for lv in self.levels]
        if self.reference:
            rows.append({"level": self.reference, "log_effect": 0.0})
        out = pd.DataFrame(rows, columns=["level", "log_effect"]).sort_values("level")
        out["factor_vs_reference"] = np.exp(out["log_effect"])
        return out.reset_index(drop=True)

    def summary(self) -> pd.DataFrame:
        """Wood parameters per parity for the typical (median) cow at the reference level,
        plus the 305-day yield."""
        rows, d = [], np.arange(1, 306, dtype=float)
        for p in PARITIES:
            a = float(np.exp(self.params[f"ln_a[{p}]"])) * self.smear_known
            b, c = float(self.params[f"b[{p}]"]), -float(self.params[f"neg_c[{p}]"])
            y = a * d ** b * np.exp(-c * d)
            rows.append({"parity_group": p, "a": a, "b": b, "c_per_day": c,
                         "peak_day": b / c if c > 0 else np.nan, "peak_litres": float(y.max()),
                         "litres_305d": float(y.sum())})
        out = pd.DataFrame(rows)
        out.attrs["preg_late_per_day"] = float(self.params["preg_late"])
        out.attrs["sigma2_cow"], out.attrs["sigma2_resid"] = self.sigma2_cow, self.sigma2_resid
        return out


def _fit_levels(f: pd.DataFrame, t: pd.DataFrame, calendar_level: bool) -> tuple[tuple[str, ...], str]:
    if not calendar_level:
        return (), ""
    ref = f.attrs.get("reference_level", "")
    return tuple(sorted(set(t["level"]) - {ref})), ref


def fit_wood_mixed(f: pd.DataFrame, calendar_level: bool = True) -> WoodMixed:
    """Wood per parity, random intercept per cow (statsmodels MixedLM, REML), plus one
    calendar level per training half-year when ``calendar_level``."""
    import statsmodels.api as sm

    t = _train_rows(f)
    levels, ref = _fit_levels(f, t, calendar_level)
    X = _wood_design(t, levels)
    keep = [c for c in X.columns if X[c].abs().sum() > 0]
    res = sm.MixedLM(np.log(t["litres"].to_numpy()), X[keep], groups=t["animal"].to_numpy()).fit(
        reml=True, method=["lbfgs", "powell"])
    params = res.fe_params.reindex(X.columns).fillna(0.0)
    u = pd.Series({k: float(v.iloc[0]) for k, v in res.random_effects.items()}, name="u")
    m = WoodMixed(name="wood", cow_effect=u, smear_known=1.0, smear_marginal=1.0,
                  sigma2_cow=float(res.cov_re.iloc[0, 0]), sigma2_resid=float(res.scale),
                  params=params, levels=levels, reference=ref)
    m._set_smearing(t)
    return m


EBM_FEATURES = ("dim", "parity_group", "days_pregnant")


@dataclass
class EbmCow(CowModel):
    model: object = None
    features: tuple[str, ...] = EBM_FEATURES
    reference: str = ""

    def linear(self, f: pd.DataFrame) -> np.ndarray:
        return self.model.predict(f[list(self.features)])

    def importances(self) -> pd.DataFrame:
        return (pd.DataFrame({"term": self.model.term_names_,
                              "importance": self.model.term_importances()})
                .sort_values("importance", ascending=False).reset_index(drop=True))

    def shape(self, term: str) -> pd.DataFrame:
        """Shape function of one main-effect term (log-litre contribution per bin)."""
        i = list(self.model.term_names_).index(term)
        g = self.model.explain_global().data(i)
        names, scores = list(g["names"]), list(g["scores"])
        if len(names) == len(scores) + 1:  # continuous: bin edges
            names = [(lo + hi) / 2 for lo, hi in zip(names[:-1], names[1:])]
        out = pd.DataFrame({"value": names, "log_effect": scores})
        if term == "level" and self.reference in set(out["value"]):
            ref = float(out.loc[out["value"] == self.reference, "log_effect"].iloc[0])
            out["factor_vs_reference"] = np.exp(out["log_effect"] - ref)
        return out


def fit_ebm(f: pd.DataFrame, extra_features: tuple[str, ...] = (), calendar_level: bool = True,
            **ebm_kwargs) -> EbmCow:
    from interpret.glassbox import ExplainableBoostingRegressor

    t = _train_rows(f)
    _, ref = _fit_levels(f, t, calendar_level)
    features = tuple(EBM_FEATURES) + (("level",) if calendar_level else ()) + tuple(extra_features)
    kw = {"interactions": 3, "random_state": 0}
    kw.update(ebm_kwargs)
    ebm = ExplainableBoostingRegressor(feature_names=list(features), **kw)
    y = np.log(t["litres"].to_numpy())
    ebm.fit(t[list(features)], y)
    u, s2u, s2e = shrunken_cow_effects(y - ebm.predict(t[list(features)]), t["animal"].to_numpy())
    m = EbmCow(name="ebm", cow_effect=u, smear_known=1.0, smear_marginal=1.0,
               sigma2_cow=s2u, sigma2_resid=s2e, model=ebm, features=features, reference=ref)
    m._set_smearing(t)
    return m


def score_cowdays(f: pd.DataFrame, pred: np.ndarray, periods=("train", "validate")) -> pd.DataFrame:
    """Cow-day errors per period on usable records (aggregates only)."""
    s = f.assign(pred=pred)
    s = s[s["usable"] & s["period"].isin(periods) & s["pred"].notna()]
    rows = []
    for p, g in s.groupby("period", sort=False):
        e = g["pred"] - g["litres"]
        rows.append({"period": p, "cow_days": len(g), "cows": g["animal"].nunique(),
                     "mean_litres": g["litres"].mean(), "mae": e.abs().mean(), "bias": e.mean(),
                     "mape_pct": 100 * (e.abs() / g["litres"]).mean(),
                     "within_10pct": float((e.abs() <= 0.1 * g["litres"]).mean())})
    return pd.DataFrame(rows)


def herd_daily(f: pd.DataFrame, pred: np.ndarray) -> pd.DataFrame:
    """Per day: recorded vs all milking cows, the naive herd estimate and the model's.

    ``selection_bias_pct``: how far the model's mean for the recorded cows sits from its
    mean for all milking cows, i.e. the error of "mean of recorded x milking" that comes
    only from which cows were measured. Milking cows whose DIM is unknown (no calving, or
    dated after the recorded dry-off) get that day's mean prediction for the cows with a
    known DIM; ``dim_unknown`` counts them so the estimated share stays visible.
    """
    known = f["dim_known"] if "dim_known" in f else pd.Series(True, index=f.index)
    s = f.assign(pred=np.where(known, pred, np.nan), rec=f["usable"],
                 y=f["litres"].where(f["usable"]), unk=~known)
    day_mean = s.groupby("date")["pred"].transform("mean")
    s["pred"] = s["pred"].fillna(day_mean)
    g = s.groupby("date")
    d = pd.DataFrame({
        "period": g["period"].first(),
        "milking": g.size(),
        "recorded": g["rec"].sum(),
        "actual_recorded": g["y"].sum(min_count=1),
        "pred_recorded": s[s["rec"]].groupby("date")["pred"].sum(),
        "pred_herd": g["pred"].sum(),
        "dim_unknown": g["unk"].sum(),
    })
    d["recorded"] = d["recorded"].astype(int)
    d["naive_herd"] = d["actual_recorded"] / d["recorded"].replace(0, np.nan) * d["milking"]
    d["selection_bias_pct"] = 100 * ((d["pred_recorded"] / d["recorded"].replace(0, np.nan))
                                     / (d["pred_herd"] / d["milking"]) - 1)
    return d


def score_herd_days(daily: pd.DataFrame, periods=("train", "validate"),
                    min_recorded: int = MIN_RECORDED_COWS) -> pd.DataFrame:
    """Day-level accuracy of the summed prediction for the recorded cows (same cows, fair)."""
    d = daily[daily["period"].isin(periods) & (daily["recorded"] >= min_recorded)]
    rows = []
    for p, g in d.groupby("period", sort=False):
        pe = 100 * (g["pred_recorded"] / g["actual_recorded"] - 1)
        rows.append({"period": p, "days": len(g), "mean_recorded": g["recorded"].mean(),
                     "mape_pct": pe.abs().mean(), "bias_pct": pe.mean(),
                     "within_10pct": float((pe.abs() <= 10).mean()),
                     "selection_bias_pct": g["selection_bias_pct"].mean()})
    return pd.DataFrame(rows)


def trailing_level(daily: pd.DataFrame, window_days: int = TRAILING_DAYS,
                   min_cow_days: int = MIN_TRAILING_COW_DAYS) -> pd.Series:
    """Per day: actual / predicted litres of the recorded cows over the previous
    ``window_days`` (the day itself excluded, so no leakage); NaN with fewer than
    ``min_cow_days`` recorded cow-days in the window."""
    d = daily[["actual_recorded", "pred_recorded", "recorded"]].fillna(0.0)
    d.index = pd.to_datetime(d.index)
    d = d.sort_index()
    r = d.rolling(f"{window_days}D", closed="left").sum()
    return (r["actual_recorded"] / r["pred_recorded"]).where(r["recorded"] >= min_cow_days)


def apply_day_factor(f: pd.DataFrame, pred: np.ndarray, factor: pd.Series) -> np.ndarray:
    return pred * f["date"].map(factor).to_numpy(dtype=float)


def scale_daily(daily: pd.DataFrame, factor: pd.Series) -> pd.DataFrame:
    """Herd days rescaled by a day factor; days without a factor are dropped."""
    fac = factor.reindex(pd.to_datetime(daily.index)).to_numpy()
    d = daily.assign(pred_recorded=daily["pred_recorded"] * fac, pred_herd=daily["pred_herd"] * fac)
    return d[np.isfinite(fac)]


def level_factor(f: pd.DataFrame, pred: np.ndarray, period: str = "recalibrate") -> float:
    """Ratio of actual to predicted litres on usable records of one period (Layer 5 seed)."""
    m = (f["usable"] & (f["period"] == period)).to_numpy()
    return float(f["litres"].to_numpy()[m].sum() / pred[m].sum()) if m.any() else float("nan")


@dataclass
class Layer2Result:
    models: dict
    cow_scores: pd.DataFrame
    herd_scores: pd.DataFrame
    level_factors: dict
    known_cow_share: pd.DataFrame
    herd_daily: dict = field(default_factory=dict)  # model -> herd-level days (raw)
    input_summary: pd.DataFrame = field(default_factory=pd.DataFrame)


def run_layer2(frame: pd.DataFrame, split: CowSplit = DEFAULT_SPLIT, models=("wood", "ebm"),
               score_test: bool = False, ebm_kwargs: dict | None = None,
               calendar_level: bool = True, trailing_days: int = TRAILING_DAYS) -> Layer2Result:
    """Fit on train, score train/validate (and recalibrate/test only when ``score_test``).

    Variants: "raw" (model as fitted), "trailing" (times the trailing level factor of the
    previous ``trailing_days``) and, with ``score_test``, "recalibrated" (test times the
    fixed level factor of the recalibrate period).
    """
    f = prepare_cowdays(frame, split)
    periods = ("train", "validate") + (("recalibrate", "test") if score_test else ())
    fitted, cow, herd, levels, dailies = {}, [], [], {}, {}
    for name in models:
        m = (fit_wood_mixed(f, calendar_level) if name == "wood"
             else fit_ebm(f, calendar_level=calendar_level, **(ebm_kwargs or {})))
        fitted[name] = m
        pred = m.predict(f)
        levels[name] = level_factor(f, pred, "recalibrate")
        daily = herd_daily(f, pred)
        trail = trailing_level(daily, trailing_days)
        daily["trailing_factor"] = trail.reindex(pd.to_datetime(daily.index)).to_numpy()
        variants = [("raw", pred, daily, periods),
                    ("trailing", apply_day_factor(f, pred, trail), scale_daily(daily, trail), periods)]
        if score_test and np.isfinite(levels[name]):
            p = pred * levels[name]
            variants.append(("recalibrated", p, herd_daily(f, p), ("test",)))
        # recalibrate / test truth stays hidden unless the test run was asked for
        dailies[name] = daily[~daily["period"].isin(["recalibrate", "test"])] if not score_test else daily
        for label, p, d, per in variants:
            cow.append(score_cowdays(f, p, per).assign(model=name, variant=label))
            herd.append(score_herd_days(d, per).assign(model=name, variant=label))
    train_cows = set(f.loc[f["usable"] & (f["period"] == "train"), "animal"])
    u = f[f["usable"] & f["period"].isin(periods)]
    share = (u.assign(known=u["animal"].isin(train_cows)).groupby("period", sort=False)["known"]
             .mean().rename("known_cow_share").reset_index())
    return Layer2Result(fitted, pd.concat(cow, ignore_index=True),
                        pd.concat(herd, ignore_index=True), levels, share, dailies,
                        input_summary(f))


def input_summary(f: pd.DataFrame) -> pd.DataFrame:
    """Per year: milking cow-days, records, usable records, unknown DIM, parity mix."""
    s = f.assign(year=f["date"].dt.year, rec=f["litres"].notna(),
                 unk=~f["dim_known"] if "dim_known" in f else False)
    u = s[s["usable"]]
    g = s.groupby("year")
    out = pd.DataFrame({
        "milking_cow_days": g.size(),
        "mean_milking_cows": g.size() / g["date"].nunique(),
        "records": g["rec"].sum(),
        "usable_records": g["usable"].sum(),
        "pct_dim_unknown": 100 * g["unk"].mean(),
        "usable_cows": u.groupby("year")["animal"].nunique(),
        "mean_usable_litres": u.groupby("year")["litres"].mean(),
    })
    mix = u.groupby(["year", "parity_group"]).size().unstack(fill_value=0)
    out = out.join(mix.add_prefix("usable_parity_"))
    out["period"] = s.groupby("year")["period"].agg(lambda x: "/".join(dict.fromkeys(x)))
    return out.reset_index().fillna(0)


def write_layer2_outputs(result: Layer2Result, out: Path) -> list[Path]:
    """Write aggregate tables only (no cow rows). Returns the files written."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "input_summary.csv": result.input_summary,
        "cow_scores.csv": result.cow_scores,
        "herd_scores.csv": result.herd_scores,
        "known_cow_share.csv": result.known_cow_share,
        "level_factors.csv": pd.DataFrame(
            [{"model": k, "level_factor_recalibrate": v} for k, v in result.level_factors.items()]),
    }
    for name, m in result.models.items():
        files[f"herd_daily_{name}.csv"] = result.herd_daily[name].reset_index()
        if isinstance(m, WoodMixed):
            w = m.summary()
            files["wood_parameters.csv"] = w
            files["wood_levels.csv"] = m.level_table()
            files["wood_variance.csv"] = pd.DataFrame([{
                "preg_late_log_per_day": w.attrs["preg_late_per_day"],
                "sigma2_cow": w.attrs["sigma2_cow"], "sigma2_resid": w.attrs["sigma2_resid"],
                "smear_known": m.smear_known, "smear_marginal": m.smear_marginal,
                "cows_with_effect": len(m.cow_effect)}])
        if isinstance(m, EbmCow):
            files["ebm_importances.csv"] = m.importances()
            for term in m.features:
                files[f"ebm_shape_{term}.csv"] = m.shape(term)
    written = []
    for name, frame in files.items():
        assert "animal" not in frame.columns, name  # aggregates only
        frame.to_csv(out / name, index=False)
        written.append(out / name)
    return written
