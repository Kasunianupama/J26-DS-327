"""Four-domain experimental features from t-7..t-1 only; no availability claims."""

from datetime import timedelta
from statistics import fmean

from components.member4_crisis_forecasting.prediction.historical_features import (
    FEATURE_NAMES as PRODUCTION_FEATURE_NAMES, production_features,
)

# Keep separate categories. Sums are counts/hours, never incidence or alarm rates.
OPTIONAL_SIGNALS = (
    ("thi_mean", "climate_thi_mean_7d", "mean"),
    ("thi_max", "climate_thi_max_7d", "max"),
    ("hours_thi_above", "climate_hours_thi_above_sum_7d", "sum"),
    ("mastitis_episodes", "biological_mastitis_sum_7d", "sum"),
    ("udder_teat_episodes", "biological_udder_teat_sum_7d", "sum"),
    ("other_health_episodes", "biological_other_health_sum_7d", "sum"),
    ("n_sessions", "operational_sessions_sum_7d", "sum"),
    ("n_blood_alarms", "operational_blood_alarms_sum_7d", "sum"),
    ("n_conductivity_alarms", "operational_conductivity_alarms_sum_7d", "sum"),
)
FEATURE_NAMES = (
    *PRODUCTION_FEATURE_NAMES,
    *(f"milk_per_cow_lag_{lag}" for lag in range(1, 8)),
    *(name for _, name, _ in OPTIONAL_SIGNALS),
    *(f"{field}_observed_days_7d" for field, _, _ in OPTIONAL_SIGNALS),
)


def integrated_features(by_date, origin, milk_source):
    """Incomplete auxiliary windows yield NaN AND observed-day coverage, not zero.

    Milk history remains mandatory and single-source. An auxiliary summary needs
    all seven values: partial sums would confound recording gaps with low burden.
    """
    production = production_features(by_date, origin, milk_source)
    if production is None:
        return None
    history = [by_date[origin - timedelta(days=lag)] for lag in range(7, 0, -1)]
    lags = tuple(by_date[origin - timedelta(days=lag)].target_litres_per_cow for lag in range(1, 8))
    values, coverage = [], []
    for field, _, operation in OPTIONAL_SIGNALS:
        observed = [getattr(day, field) for day in history if getattr(day, field) is not None]
        coverage.append(float(len(observed)))
        if len(observed) != 7:
            values.append(float("nan"))
        else:
            values.append(float(fmean(observed) if operation == "mean" else
                                max(observed) if operation == "max" else sum(observed)))
    return (*production, *lags, *values, *coverage)
