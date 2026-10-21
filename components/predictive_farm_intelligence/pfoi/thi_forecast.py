"""Experimental daily maximum THI forecasts, separate from the milk/herd model.

v1 (``forecast_thi``) fits annual and half-year seasonal harmonics to up to three
years of complete weather. A recent residual adjustment decays with a fixed, assumed
seven-day time constant.

v2 (``forecast_thi_daily``) separates the seasonal pattern from day-to-day changes:

* **Seasonal part:** three harmonics fitted with recency weights (recent years count
  more), so a warmer or cooler recent period moves the curve.
* **Daily part:** the anomaly (THI minus seasonal) of the last day, the two days before
  it, and the 7- and 30-day mean anomalies. For every lead time a separate ridge
  regression learns how much of each survives that many days later. Nothing about the
  decay is assumed; a fast change (one hot day) and a slow one (a warm month) may fade
  at different rates. Between ``taper_days`` (20 and 40 days ahead) the daily part
  hands over gradually to the seasonal curve, which alone is used after that: in the
  development back-test the daily terms added noise beyond 30 days, and a hard cut put
  a visible step in the line.
* **Uncertainty:** the 10th/90th percentile of that lead's in-sample errors, and the
  share of past errors that would put the day above each heat threshold (the chance of
  a hot day). In-sample errors are widened by ``error_scale`` (1.1, from the
  development back-test's band coverage). Calibration must be checked with
  ``thi_backtest``.

Both are statistical baselines, not validated weather services. Later observations are
never used in fitting. No accuracy or coverage is claimed until the owner's back-test.
"""
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

V1_METHOD = "seasonal_harmonics_recent_residual_v1"
V2_METHOD = "seasonal_recency_daily_anomaly_v2"
V2_FEATURES = ("anomaly_last_day", "anomaly_day_before", "anomaly_2_days_before",
               "anomaly_mean_7d", "anomaly_mean_30d")


def _design(dates: pd.DatetimeIndex) -> np.ndarray:
    return _harmonics(dates, 2)


def _harmonics(dates: pd.DatetimeIndex, k: int) -> np.ndarray:
    phase = 2 * np.pi * ((dates - pd.Timestamp("2000-01-01")).days.to_numpy() / 365.2425)
    cols = [np.ones(len(dates))]
    for j in range(1, k + 1):
        cols += [np.sin(j * phase), np.cos(j * phase)]
    return np.column_stack(cols)


def _history(daily: pd.DataFrame, origin: date, weather_lag_days: int,
             max_days: int) -> tuple[pd.Series, pd.Timestamp]:
    """Complete, finite daily max THI on or before ``origin - lag`` (at most ``max_days``)."""
    cutoff = pd.Timestamp(origin) - pd.Timedelta(days=max(1, weather_lag_days))
    days = pd.to_datetime(daily["date"])
    values = pd.to_numeric(daily["thi_max"], errors="coerce")
    complete = daily["weather_is_complete"].astype("boolean").fillna(False)
    valid = complete & np.isfinite(values) & (days <= cutoff) & (days > cutoff - pd.Timedelta(days=max_days))
    history = pd.Series(values.loc[valid].to_numpy(), index=pd.DatetimeIndex(days.loc[valid])).sort_index()
    # Duplicate dates are input errors; do not give them extra fitting weight.
    return history.groupby(level=0).mean(), cutoff


def _usable(history: pd.Series, cutoff: pd.Timestamp) -> bool:
    """At least a year of distinct records, the latest no more than 14 days before the cutoff."""
    if len(history) < 365 or (history.index[-1] - history.index[0]).days < 364:
        return False
    return (cutoff - history.index[-1]).days <= 14


def _empty(method: str, history: pd.Series | None = None) -> dict:
    result = {"status": "unavailable", "method": method, "trained_through": None,
              "n_train": 0, "predictions": []}
    if history is not None:
        result["n_train"] = len(history)
        if len(history):
            result["trained_through"] = history.index[-1].date().isoformat()
    return result


def forecast_thi(daily: pd.DataFrame, origin: date, weather_lag_days: int = 6,
                 ahead_days: int = 90) -> dict:
    """v1: predict daily max THI using only complete records available at ``origin``."""
    if daily.empty or ahead_days <= 0:
        return _empty(V1_METHOD)
    history, cutoff = _history(daily, origin, weather_lag_days, 1096)
    result = _empty(V1_METHOD, history)
    if not _usable(history, cutoff):
        return result
    design = _design(history.index)
    coefficients = np.linalg.lstsq(design, history.to_numpy(), rcond=None)[0]
    recent = history.index >= history.index[-1] - pd.Timedelta(days=13)
    adjustment = float(np.mean((history.to_numpy() - design @ coefficients)[recent]))
    targets = pd.date_range(pd.Timestamp(origin), periods=ahead_days, freq="D")
    lead = (targets - history.index[-1]).days.to_numpy()
    predicted = _design(targets) @ coefficients + adjustment * np.exp(-lead / 7.0)
    result.update(status="experimental", predictions=[
        {"date": day.date().isoformat(), "thi_max": round(float(value), 2)}
        for day, value in zip(targets, predicted)
    ])
    return result


# --------------------------------------------------------------------------- v2

@dataclass(frozen=True)
class DailyThiConfig:
    history_days: int = 1826        # up to five years of complete weather
    half_life_days: float = 365.0   # weight of a day halves every year back
    harmonics: int = 3
    ridge: float = 10.0             # pull of the standardised daily terms toward zero
    min_rows: int = 180             # training pairs needed at every lead
    band: tuple[float, float] = (0.1, 0.9)
    # Development back-test 2017-2023 (owner's aggregates): beyond 30 days ahead the
    # daily terms made v2 worse than climatology, so the daily part fades out linearly
    # between these days ahead (a hard cut at 30 put a step in the line).
    taper_days: tuple[int, int] = (20, 40)
    # In-sample errors are too narrow (10-90% band held 75-78%, not 80%). For a
    # roughly normal error, 80% needs 1.28 sd and 76% covers 1.17 sd: 1.28 / 1.17 = 1.1.
    # Applied to the band and the hot-day chances alike.
    error_scale: float = 1.1


def _anomaly_features(anomaly: np.ndarray) -> np.ndarray:
    """Daily-change terms at each day, from that day and earlier days only."""
    a = pd.Series(anomaly)
    return np.column_stack([a, a.shift(1), a.shift(2),
                            a.rolling(7, min_periods=4).mean(),
                            a.rolling(30, min_periods=15).mean()])


def _lead_fit(features: np.ndarray, anomaly: np.ndarray, weights: np.ndarray,
              lead: int, cfg: DailyThiConfig):
    """Ridge regression of the anomaly ``lead`` days later on today's daily-change terms."""
    X, y, w = features[:-lead], anomaly[lead:], weights[lead:]
    keep = np.isfinite(y) & np.isfinite(X).all(axis=1)
    if keep.sum() < cfg.min_rows:
        return None
    X, y, w = X[keep], y[keep], w[keep]
    mu = np.average(X, axis=0, weights=w)
    sd = np.sqrt(np.average((X - mu) ** 2, axis=0, weights=w))
    sd = np.where(sd > 0, sd, 1.0)
    A = np.column_stack([np.ones(len(y)), (X - mu) / sd])
    penalty = np.diag([0.0] + [cfg.ridge] * X.shape[1])
    AtW = A.T * w
    beta = np.linalg.solve(AtW @ A + penalty, AtW @ y)
    return mu, sd, beta, y - A @ beta


def forecast_thi_daily(daily: pd.DataFrame, origin: date, weather_lag_days: int = 6,
                       ahead_days: int = 90, thresholds: dict[str, float] | None = None,
                       cfg: DailyThiConfig = DailyThiConfig()) -> dict:
    """v2: seasonal curve plus learned day-to-day persistence, with hot-day chances.

    ``thresholds`` maps a name to a THI level (e.g. the herd's ``knot_p75``); by default
    the 75th and 90th percentiles of the training history. Each prediction gives the
    chance that the day's max THI is above each threshold.
    """
    if daily.empty or ahead_days <= 0:
        return _empty(V2_METHOD)
    history, cutoff = _history(daily, origin, weather_lag_days, cfg.history_days)
    result = _empty(V2_METHOD, history)
    if not _usable(history, cutoff):
        return result
    last = history.index[-1]
    days = pd.date_range(history.index[0], last)
    y = history.reindex(days).to_numpy()
    weights = 0.5 ** ((last - days).days.to_numpy() / cfg.half_life_days)
    seasonal_X = _harmonics(days, cfg.harmonics)
    ok = np.isfinite(y)
    root = np.sqrt(weights[ok])
    coef = np.linalg.lstsq(seasonal_X[ok] * root[:, None], y[ok] * root, rcond=None)[0]
    anomaly = y - seasonal_X @ coef
    features = _anomaly_features(anomaly)
    now = features[-1]
    if thresholds is None:
        thresholds = {"p75": float(np.percentile(history, 75)), "p90": float(np.percentile(history, 90))}
    thresholds = {k: float(v) for k, v in thresholds.items() if v is not None and np.isfinite(v)}

    targets = pd.date_range(pd.Timestamp(origin), periods=ahead_days, freq="D")
    seasonal = _harmonics(targets, cfg.harmonics) @ coef
    seasonal_errors = anomaly[np.isfinite(anomaly)]
    predictions, persistence = [], {}
    seasonal_resid = seasonal_errors * cfg.error_scale
    start, end = cfg.taper_days
    for i, (day, lead, base) in enumerate(zip(targets, (targets - last).days.to_numpy(), seasonal)):
        weight = float(np.clip((end - i) / max(1, end - start), 0.0, 1.0))  # share of the daily part
        if weight == 0.0:
            mean, parts = float(base), [(1.0, seasonal_resid)]
        else:
            fit = _lead_fit(features, anomaly, weights, int(lead), cfg)
            if fit is None:
                return result
            mu, sd, beta, resid = fit
            # A missing recent term counts as its usual value (no information either way).
            z = np.where(np.isfinite(now), (now - mu) / sd, 0.0)
            mean = float(base + weight * (beta[0] + z @ beta[1:]))
            parts = [(weight, resid * cfg.error_scale), (1.0 - weight, seasonal_resid)]
            if int(lead) in (7, 14, 30):
                # A one-unit warmer last day enters that day's term and both mean terms.
                share = beta[1] / sd[0] + beta[4] / sd[3] / 7 + beta[5] / sd[4] / 30
                persistence[str(int(lead))] = round(float(share), 3)
        # Band and chances blend the two error sets in the same proportions as the mean.
        lo, hi = (sum(w * float(np.quantile(r, q)) for w, r in parts if w > 0) for q in cfg.band)
        chance = {k: sum(w * float(np.mean(mean + r > t)) for w, r in parts if w > 0)
                  for k, t in thresholds.items()}
        predictions.append({
            "date": day.date().isoformat(), "thi_max": round(mean, 2),
            "seasonal": round(float(base), 2),
            "lower": round(mean + lo, 2), "upper": round(mean + hi, 2),
            "p_above": {k: round(v, 3) for k, v in chance.items()},
        })
    result.update(status="experimental", predictions=predictions,
                  thresholds={k: round(t, 2) for k, t in thresholds.items()},
                  band=list(cfg.band), taper_days=list(cfg.taper_days),
                  # Share of a one-day, 1-unit anomaly on the last known day still
                  # present N days later; learned from the data, not assumed.
                  persistence_by_lead=persistence)
    return result


METHODS = {"v1": forecast_thi, "v2": forecast_thi_daily}
