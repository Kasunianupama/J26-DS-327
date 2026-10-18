"""Benchmark forecasts to compare against: persistence, seasonal naive, ETS and SARIMA.

All benchmarks see only history dated before the origin. They work on a series of
period means (litres per day, or animals) and return a mean per future period; callers
multiply by period length where a total is needed.

* persistence: the last complete period's mean.
* seasonal naive: the same period one year earlier.
* ETS: Holt-Winters exponential smoothing (statsmodels), damped additive trend, additive
  seasonality when there are at least two full seasons.
* SARIMA: (1,0,0)(0,1,1)s on the last contiguous run of at least three seasons
  (monthly only).
Missing periods break a series: models use the last contiguous run before the origin.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

MIN_ETS = 8


def last_run(series: pd.Series) -> pd.Series:
    """Longest tail of the series without missing values (index assumed regular)."""
    s = series.sort_index()
    if not len(s):
        return s
    isna = s.isna().to_numpy()
    if not isna.any():
        return s
    last_gap = np.where(isna)[0].max()
    return s.iloc[last_gap + 1:]


def ets_forecast(series: pd.Series, steps: int, season: int | None) -> np.ndarray | None:
    from statsmodels.tsa.holtwinters import ExponentialSmoothing

    y = last_run(series).astype(float)
    if len(y) < MIN_ETS:
        return None
    seasonal = "add" if season and len(y) >= 2 * season else None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = ExponentialSmoothing(
                y.to_numpy(), trend="add", damped_trend=True, seasonal=seasonal,
                seasonal_periods=season if seasonal else None, initialization_method="estimated",
            ).fit()
            out = np.asarray(model.forecast(steps), dtype=float)
    except Exception:  # noqa: BLE001 - a failed benchmark fit is reported as missing
        return None
    return out if np.isfinite(out).all() else None


def sarima_forecast(series: pd.Series, steps: int, season: int = 12) -> np.ndarray | None:
    from statsmodels.tsa.statespace.sarimax import SARIMAX

    y = last_run(series).astype(float)
    if len(y) < 3 * season:
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = SARIMAX(y.to_numpy(), order=(1, 0, 0), seasonal_order=(0, 1, 1, season),
                            enforce_stationarity=False, enforce_invertibility=False).fit(disp=False)
            out = np.asarray(model.forecast(steps), dtype=float)
    except Exception:  # noqa: BLE001
        return None
    return out if np.isfinite(out).all() else None


def persistence_value(series: pd.Series) -> float | None:
    s = series.dropna()
    return None if not len(s) else float(s.sort_index().iloc[-1])
