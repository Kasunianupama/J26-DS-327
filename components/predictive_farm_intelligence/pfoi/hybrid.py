"""PFOI 1.3 research specialists. Pure aggregate inputs; no I/O or database access.

All selection uses forecasts actually issued earlier and labels completed by issuance.
The abortion model estimates recorded counts, not a causal pregnancy-loss risk.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import product
import hashlib
import json

import numpy as np
import pandas as pd

VERSION = "pfoi-1.3.0-dev"


@dataclass(frozen=True)
class HybridConfig:
    min_train: int = 24
    min_gate: int = 12
    half_life_days: float = 180.0
    ridge: float = 10.0
    improvement_margin: float = .02
    max_stale_days: int = 7
    min_recent_days: int = 14
    abortion_min_days: int = 60
    abortion_half_life_days: float = 30.0
    abortion_prior_days: float = 30.0
    interval_min: int = 19

    def __post_init__(self):
        if min(self.min_train, self.min_gate, self.min_recent_days,
               self.abortion_min_days, self.interval_min) < 1:
            raise ValueError("Minimum sample sizes must be positive")
        if min(self.half_life_days, self.ridge, self.abortion_half_life_days,
               self.abortion_prior_days) <= 0 or self.max_stale_days < 1:
            raise ValueError("Scales must be positive")
        if not 0 <= self.improvement_margin < 1:
            raise ValueError("Improvement margin must be in [0, 1)")

    def identity(self, base: dict) -> str:
        payload = dict(version=VERSION, config=asdict(self), base=base)
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def dated(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["date"] = pd.to_datetime(out.date, errors="raise")
    if out.date.isna().any() or out.date.duplicated().any():
        raise ValueError("Aggregate dates must be present and unique")
    return out.sort_values("date").set_index("date")


def completed(records: list[dict], origin, **filters) -> list[dict]:
    o = pd.Timestamp(origin)
    return [r for r in records if pd.Timestamp(r["origin"]) < o
            and pd.Timestamp(r["period_end"]) <= o
            and np.isfinite(r.get("actual", np.nan))
            and all(r.get(k) == v for k, v in filters.items())]


def milk_context(history: pd.DataFrame, origin, projected: pd.DataFrame,
                 cfg: HybridConfig) -> tuple[dict | None, str]:
    """Only pre-origin trusted, current-source milk sets features and the anchor.

    ``projected`` is origin-issued model output, never recorded future observations.
    Effective litres/cow is a recording-dependent feature, not a biological yield.
    """
    o = pd.Timestamp(origin)
    past = history.loc[history.index < o]
    if past.empty or past.source.dropna().empty:
        return None, "no_source_history"
    source = past.source.dropna().iloc[-1]
    valid = (past.trusted.fillna(False).astype(bool) & past.source.eq(source)
             & np.isfinite(past.milk) & past.milk.ge(0))
    recent = past.loc[(past.index >= o-pd.Timedelta(days=28)) & valid]
    if len(recent) < cfg.min_recent_days:
        return None, "insufficient_trusted_recent_milk"
    if (o-recent.index.max()).days > cfg.max_stale_days:
        return None, "stale_milk"
    anchor = float(recent.milk.iloc[-1])
    if anchor <= 0:
        return None, "nonpositive_latest_milk"
    avg = float(recent.milk.mean())
    last7 = recent.loc[recent.index >= o-pd.Timedelta(days=7), "milk"]
    prev7 = recent.loc[(recent.index >= o-pd.Timedelta(days=14))
                       & (recent.index < o-pd.Timedelta(days=7)), "milk"]
    cows = recent.milking.where(recent.milking.gt(0)).dropna()
    if cows.empty:
        return None, "missing_recent_milking_count"
    count = float(cows.iloc[-1])
    # Windows without observations are explicit: missing trend is neutral with a mask.
    trend = ((float(last7.mean())-float(prev7.mean()))/anchor
             if len(last7) >= 3 and len(prev7) >= 3 else 0.)
    missing_trend = float(len(last7) < 3 or len(prev7) < 3)
    date0 = pd.Timestamp(projected.date.iloc[0])
    phase = 2*np.pi*(date0.month-1)/12
    lead = (date0-o).days/365.
    history_x = np.array([avg/anchor-1, trend, missing_trend,
                          float(recent.milk.std(ddof=0))/anchor,
                          len(recent)/28, (o-recent.index.max()).days/28,
                          np.log1p(anchor/count), np.sin(phase), np.cos(phase), lead])
    pipeline_x = np.r_[history_x,
        float(projected.herd_milk.mean())/anchor-1,
        float(projected.milking.mean())/count-1,
        float(projected.calvings.sum())/count,
        float(projected.dry_offs.sum())/count]
    if not np.isfinite(pipeline_x).all():
        return None, "missing_projected_features"
    return dict(source=source, anchor=anchor, history_x=history_x,
                pipeline_x=pipeline_x), "ok"


def change_forecast(training: list[dict], context: dict, origin, days: int,
                    feature: str, cfg: HybridConfig) -> float | None:
    """Recency-weighted ridge predicts change relative to the last known daily value."""
    rows = completed(training, origin, source=context["source"])
    rows = [r for r in rows if feature in r and r["anchor"] > 0]
    if len(rows) < cfg.min_train:
        return None
    x = np.stack([r[feature] for r in rows])
    y = np.array([r["actual"]/r["days"]/r["anchor"]-1 for r in rows])
    age = np.array([(pd.Timestamp(origin)-pd.Timestamp(r["period_end"])).days for r in rows])
    w = .5**(age/cfg.half_life_days)
    mean = np.average(x, axis=0, weights=w)
    sd = np.sqrt(np.average((x-mean)**2, axis=0, weights=w))
    sd = np.maximum(sd, 1e-6)
    z = np.c_[np.ones(len(x)), (x-mean)/sd]
    penalty = np.eye(z.shape[1])*cfg.ridge
    penalty[0, 0] = 0
    coef = np.linalg.solve(z.T@(w[:, None]*z)+penalty, z.T@(w*y))
    query = np.r_[1., (context[feature]-mean)/sd]
    return max(0., float(context["anchor"]*days*(1+query@coef)))


def choose_weights(records: list[dict], origin, names: tuple[str, ...],
                   cfg: HybridConfig, fallback: str) -> tuple[dict[str, float], int]:
    """Small convex grid; require a margin over the fallback on identical past periods.

    Each caller supplies one series/grain/horizon/source. No current label is consulted.
    Missing specialists do not prevent comparisons among available references.
    """
    if fallback not in names:
        raise ValueError("Fallback must be an available model")
    rows = [r for r in completed(records, origin)
            if all(np.isfinite(r.get(n, np.nan)) for n in names)]
    default = {n: float(n == fallback) for n in names}
    if len(rows) < cfg.min_gate:
        return default, len(rows)
    age = np.array([(pd.Timestamp(origin)-pd.Timestamp(r["period_end"])).days for r in rows])
    w = .5**(age/cfg.half_life_days)
    forecasts = np.array([[r[n] for n in names] for r in rows])
    actual = np.array([r["actual"] for r in rows])
    loss0 = np.average(np.abs(forecasts[:, names.index(fallback)]-actual), weights=w)
    best, best_loss = default, loss0
    for ticks in product(range(5), repeat=len(names)):
        if sum(ticks) != 4:
            continue
        weights = np.array(ticks)/4
        loss = np.average(np.abs(forecasts@weights-actual), weights=w)
        if loss < best_loss and loss < loss0*(1-cfg.improvement_margin):
            best, best_loss = dict(zip(names, weights.tolist())), loss
    return best, len(rows)


@dataclass(frozen=True)
class AbortionPosterior:
    shape: float
    rate_days: float
    n_days: int

    @property
    def daily_mean(self) -> float:
        return self.shape/self.rate_days

    def predictive(self, days: int) -> tuple[float, float, float]:
        """Gamma-Poisson / negative-binomial count range, including parameter uncertainty.

        This candidate range assumes a stable latent count intensity over the period;
        it is not a calibrated range for the coupled or fused forecast.
        """
        from scipy.stats import nbinom
        if days < 1:
            raise ValueError("Period length must be positive")
        p = self.rate_days/(self.rate_days+days)
        lo, hi = nbinom.ppf([.05, .95], self.shape, p)
        return self.daily_mean*days, float(lo), float(hi)


def abortion_posterior(history: pd.DataFrame, origin, cfg: HybridConfig) -> AbortionPosterior | None:
    """Discounted recorded counts/day, with a past-only long-term shrinkage prior.

    Missing events remain missing. At least 60 of the last 90 calendar days are needed.
    No denominator is mislabelled as pregnant animals when that exposure is unavailable.
    """
    o = pd.Timestamp(origin)
    past = history.loc[(history.index < o) & (history.index >= o-pd.Timedelta(days=730))]
    values = past.abortions.where(np.isfinite(past.abortions) & past.abortions.ge(0)).dropna()
    recent = values.loc[values.index >= o-pd.Timedelta(days=90)]
    if len(recent) < cfg.abortion_min_days or (o-recent.index.max()).days > cfg.max_stale_days:
        return None
    old = values.loc[values.index < o-pd.Timedelta(days=90)]
    # Weak proper prior if no earlier history; otherwise shrink towards earlier counts.
    prior_mean = float(old.mean()) if len(old) else .5/cfg.abortion_prior_days
    w = .5**(np.array((o-recent.index).days)/cfg.abortion_half_life_days)
    return AbortionPosterior(.5+prior_mean*cfg.abortion_prior_days+float(w@recent.to_numpy()),
                             cfg.abortion_prior_days+float(w.sum()), len(recent))


def coupled_hazard(state, base_hazard: float, posterior: AbortionPosterior | None,
                   weight: float) -> float:
    """One origin-level hazard feeds the entire engine, rather than overwriting events.

    Mapping a count intensity onto the known pregnant starting population is an
    assumption, not an estimated exposure-adjusted biological risk. The engine then
    evolves the population at risk and its milk/calving consequences together.
    """
    if not 0 <= weight <= 1 or not 0 <= base_hazard <= 1:
        raise ValueError("Hazard and weight must be probabilities")
    risk = float(state.heifer_preg.sum()+state.dry_preg.sum()+state.milk_preg.sum())
    if posterior is None or weight == 0 or risk <= 0:
        return base_hazard
    candidate = min(1., posterior.daily_mean/risk)
    return float((1-weight)*base_hazard+weight*candidate)


def residual_interval(records: list[dict], origin, forecast: float, scale: float,
                      cfg: HybridConfig, coverage: float = .9) -> tuple[float | None, float | None, int]:
    """90% absolute-error range from this forecast's own completed issued errors.

    Normalize by the origin-known scale, never by a possibly near-zero prediction.
    No exchangeability/conditional-coverage guarantee is claimed for adaptive history.
    """
    if not 0 < coverage < 1 or not np.isfinite(scale) or scale <= 0:
        raise ValueError("Coverage and scale must be positive and finite")
    rows = [r for r in completed(records, origin) if r.get("scale", 0) > 0
            and np.isfinite(r.get("fused", np.nan))]
    if len(rows) < cfg.interval_min:
        return None, None, len(rows)
    scores = np.sort([abs(r["actual"]-r["fused"])/r["scale"] for r in rows])
    rank = min(len(scores), int(np.ceil((len(scores)+1)*coverage)))
    spread = float(scores[rank-1]*scale)
    return max(0., forecast-spread), forecast+spread, len(rows)


def reconcile_milk(daily: pd.DataFrame, monthly: dict[pd.Timestamp, float]) -> pd.DataFrame:
    """One coherent milk path: each daily month sums to its selected monthly total.

    All herd states/events stay on the coupled engine path. Statistical milk changes
    are effective-yield corrections, with no unsupported claim of changed biology.
    """
    out = daily.copy()
    dates = pd.to_datetime(out.date)
    for start, total in monthly.items():
        if not np.isfinite(total) or total < 0:
            raise ValueError("Monthly milk must be finite and nonnegative")
        mask = dates.dt.to_period("M").eq(pd.Timestamp(start).to_period("M"))
        part = out.loc[mask, "herd_milk"]
        expected = pd.Timestamp(start).days_in_month
        if len(part) != expected or not np.isfinite(part).all() or (part < 0).any():
            raise ValueError("Reconciliation needs a complete finite daily month")
        out.loc[mask, "herd_milk"] = part*total/part.sum() if part.sum() > 0 else total/len(part)
    return out
