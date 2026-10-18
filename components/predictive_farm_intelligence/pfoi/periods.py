"""Turn daily series into weekly/monthly horizons.

Stocks are period means of daily values and events are period sums, matching
`model_input.period_panel`. Monthly origins are the 1st of a month (horizon 1 = that
month); weekly origins are Mondays (horizon 1 = the week starting at the origin); daily
horizons count days from the origin (horizon 1 = the origin day).
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

GRAINS = ("monthly", "weekly", "daily")
HORIZONS = {"monthly": (1, 3, 6, 12), "weekly": (1, 4, 8, 13), "daily": (1, 7, 14)}


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    return date(d.year + y, m + 1, 1)


def check_origin(origin: date, grain: str) -> None:
    if grain == "monthly" and origin.day != 1:
        raise ValueError("monthly origins must be the first day of a month")
    if grain == "weekly" and origin.weekday() != 0:
        raise ValueError("weekly origins must be Mondays")
    if grain not in GRAINS:
        raise ValueError(f"unknown grain {grain!r}")


def period_bounds(origin: date, grain: str, horizon: int) -> tuple[date, date]:
    """[start, end) of the period at ``horizon`` from ``origin``."""
    check_origin(origin, grain)
    if horizon < 1:
        raise ValueError("horizon starts at 1")
    if grain == "monthly":
        return _add_months(origin, horizon - 1), _add_months(origin, horizon)
    if grain == "daily":
        start = origin + timedelta(days=horizon - 1)
        return start, start + timedelta(days=1)
    start = origin + timedelta(days=7 * (horizon - 1))
    return start, start + timedelta(days=7)


def horizon_days(origin: date, grain: str, max_horizon: int) -> int:
    return (period_bounds(origin, grain, max_horizon)[1] - origin).days


def aggregate(
    daily: pd.DataFrame,
    origin: date,
    grain: str,
    horizons: tuple[int, ...],
    stock_cols: tuple[str, ...],
    event_cols: tuple[str, ...],
) -> pd.DataFrame:
    """Long frame (horizon, period_start, period_end, series, value); only complete periods."""
    dates = pd.to_datetime(daily["date"]).dt.date
    rows = []
    for h in horizons:
        start, end = period_bounds(origin, grain, h)
        mask = (dates >= start) & (dates < end)
        if mask.sum() != (end - start).days:
            continue
        part = daily.loc[mask]
        for col in stock_cols:
            rows.append((h, start, end, col, float(part[col].mean())))
        for col in event_cols:
            rows.append((h, start, end, col, float(part[col].sum())))
    return pd.DataFrame(rows, columns=["horizon", "period_start", "period_end", "series", "value"])
