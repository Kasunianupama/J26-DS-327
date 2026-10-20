"""Breaks the model can see at the forecast date (PP1 improvement 1a, docs/pp1_plan.md).

After a break, corrections learned from earlier errors describe a herd or a recording
situation that no longer exists (the 2024-25 recovery: the correction layer added about
+83 milking cows in the wrong direction). With ``break reset`` the correction layer uses only
errors from forecast dates on or after the latest break known at the forecast date, so it
starts again from the structural forecast and relearns.

Rules (fixed before evaluation, herd-level daily aggregates only; a break is dated on the
day it becomes visible, so it is known at every later forecast date):

* herd break: the 28-day mean of the herd size differs by more than ``HERD_CHANGE`` (10 %)
  from the 28-day mean 90 days earlier;
* milk break: the first trusted milk day after at least ``MILK_GAP_DAYS`` (28) days
  without one;
* breaks closer than ``MERGE_DAYS`` (60) to the previous one are merged into it.

These are not the hand-dated episodes in ``episodes.BREAKS`` (evaluation labels only).
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

HERD_CHANGE = 0.10
HERD_WINDOW = 28
HERD_LAG = 90
MILK_GAP_DAYS = 28
MERGE_DAYS = 60


def detect_breaks(daily: pd.DataFrame) -> list[date]:
    """Break dates from a daily frame with ``date``, ``n_herd`` and (optionally) the milk
    target's ``is_scoreable`` / ``target_litres``. Uses each day's past only."""
    d = daily.copy()
    d.index = pd.to_datetime(d["date"])
    d = d.sort_index()
    d = d[~d.index.duplicated()].reindex(pd.date_range(d.index.min(), d.index.max()))
    found: list[date] = []
    if "n_herd" in d:
        m = pd.to_numeric(d["n_herd"], errors="coerce").rolling(HERD_WINDOW, min_periods=HERD_WINDOW // 2).mean()
        before = m.shift(HERD_LAG)
        change = (m / before - 1.0).abs()
        hit = change > HERD_CHANGE
        found += [ts.date() for ts in hit.index[hit & ~hit.shift(1, fill_value=False)]]
    if "is_scoreable" in d:
        ok = d["is_scoreable"].astype("boolean").fillna(False).astype(bool)
        if "target_litres" in d:
            ok &= pd.to_numeric(d["target_litres"], errors="coerce").notna()
        run = 0
        for ts, v in ok.items():
            if v and run >= MILK_GAP_DAYS:
                found.append(ts.date())
            run = 0 if v else run + 1
    out: list[date] = []
    for b in sorted(set(found)):
        if not out or (b - out[-1]).days >= MERGE_DAYS:
            out.append(b)
    return out


def latest_break(origin, breaks) -> np.datetime64 | None:
    """The latest break known at ``origin`` (dated before it), or None."""
    o = pd.Timestamp(origin).date()
    past = [b for b in (breaks or []) if b < o]
    return np.datetime64(max(past)) if past else None


def since_mask(origins: np.ndarray, origin, breaks) -> np.ndarray:
    """True for errors whose forecast date is on or after the latest break known at ``origin``."""
    b = latest_break(origin, breaks)
    if b is None:
        return np.ones(len(origins), dtype=bool)
    return origins >= b


def break_table(breaks: list[date], start: date | None = None) -> pd.DataFrame:
    """Breaks as a small table for reports (dates only, herd level)."""
    rows = [{"break_date": b} for b in breaks if start is None or b >= start]
    return pd.DataFrame(rows)

