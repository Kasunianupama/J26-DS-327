"""Allowlisted, strictly lagged production features; no quality flags as inputs."""

from datetime import date, timedelta
from math import isfinite
from statistics import fmean, pstdev

FEATURE_NAMES = ("last_per_cow", "mean_7d", "std_7d", "recent_minus_earlier_mean")


def production_features(by_date, origin: date, milk_source: str) -> tuple[float, ...] | None:
    """Only t-7..t-1. Never read origin/future values, scoreability, or alarms.

    These are lags by observation date, not evidence of genuine availability.
    """
    history = [by_date.get(origin - timedelta(days=lag)) for lag in range(7, 0, -1)]
    if any(day is None or day.target_source != milk_source
           or day.target_litres_per_cow is None for day in history):
        return None
    values = [day.target_litres_per_cow for day in history]
    features = (values[-1], fmean(values), pstdev(values), fmean(values[-3:]) - fmean(values[:4]))
    return features if all(isfinite(value) for value in features) else None
