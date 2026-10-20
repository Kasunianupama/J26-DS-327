"""Record-quality bands and labelled breaks (docs/targets.md, "Known disruption episodes").

Bands describe how far a scored period's records can be trusted. They are computed from
herd-level daily aggregates only (identified share of DelPro milk, gap days, litres per
recorded milking cow-day) and are used to report scores separately, never to change a
forecast. Breaks are the dated episodes the recovery metrics are measured from.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

NORMAL, DEGRADED, UNVERIFIED, GAP = "normal", "degraded", "unverified", "gap"
VERIFIED_BANDS = (NORMAL, DEGRADED)
NORMAL_MIN_SHARE = 0.6
VERIFIED_MIN_SHARE = 0.2
# User's farm knowledge (2026-10-19): above 20 L per cow a day is not realistic.
MAX_LITRES_PER_COW_DAY = 20.0


@dataclass(frozen=True)
class Break:
    code: str
    kind: str
    start: date


# From the monthly aggregates of 2026-10-19 (episode_checks.sql). Gap breaks are dated
# at the first day the target is back, because recovery is measured from there.
BREAKS = (
    Break("E1", "herd contraction", date(2022, 9, 1)),
    Break("E5a", "end of milk gap", date(2022, 12, 1)),
    Break("E2", "abortion surge", date(2023, 11, 1)),
    Break("E3", "herd contraction", date(2024, 3, 1)),
    Break("E5b", "end of milk gap", date(2024, 7, 1)),
    Break("E5c", "end of milk gap", date(2025, 9, 8)),
)
RECOVERY_BUCKETS = ((0, 3, "0-2 months"), (3, 6, "3-5 months"), (6, 12, "6-11 months"),
                    (12, 10_000, "12+ months"))
NO_BREAK = "before any break"


def daily_quality(target: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    """One row per day: date, source, identified_share, gap, litres per recorded milking cow."""
    t = target[["date", "target_source", "target_litres", "identified_share", "data_gap"]].copy()
    t["date"] = pd.to_datetime(t["date"]).dt.date
    p = panel[["date", "milking"]].copy()
    p["date"] = pd.to_datetime(p["date"]).dt.date
    q = t.merge(p, on="date", how="left")
    q["gap"] = pd.to_numeric(q["data_gap"], errors="coerce").fillna(0) > 0
    q["litres_per_cow"] = (q["target_litres"] / q["milking"]).where(q["milking"] > 0)
    return q[["date", "target_source", "identified_share", "gap", "target_litres", "milking",
              "litres_per_cow"]]


def period_band(q: pd.DataFrame, start: date, end: date) -> str:
    """Band of the days in [start, end) of a ``daily_quality`` frame."""
    part = q[(q["date"] >= start) & (q["date"] < end)]
    if not len(part):
        return GAP
    if part["gap"].any():
        return GAP
    delpro = part[part["target_source"] == "delpro"]
    if not len(delpro):
        return NORMAL  # shipment era: no identification to lose
    litres, cows = delpro["target_litres"].sum(), delpro["milking"].sum()
    if cows > 0 and litres / cows > MAX_LITRES_PER_COW_DAY:
        return UNVERIFIED
    share = delpro["identified_share"].mean()
    if pd.isna(share) or share < VERIFIED_MIN_SHARE:
        return UNVERIFIED
    return NORMAL if share >= NORMAL_MIN_SHARE else DEGRADED


def add_bands(errors: pd.DataFrame, q: pd.DataFrame) -> pd.DataFrame:
    """Add ``band`` per scored period (computed once per distinct period)."""
    out = errors.copy()
    starts = pd.to_datetime(out["period_start"]).dt.date
    ends = pd.to_datetime(out["period_end"]).dt.date
    cache = {(s, e): period_band(q, s, e) for s, e in set(zip(starts, ends))}
    out["band"] = [cache[(s, e)] for s, e in zip(starts, ends)]
    return out


def months_since_break(origin: date, breaks=BREAKS) -> tuple[str | None, float]:
    """(code, months) of the latest break on or before ``origin``; (None, nan) if none."""
    past = [b for b in breaks if b.start <= origin]
    if not past:
        return None, np.nan
    b = max(past, key=lambda x: x.start)
    months = (origin.year - b.start.year) * 12 + origin.month - b.start.month
    return b.code, float(months - (origin.day < b.start.day))  # whole months completed


def recovery_bucket(months: float) -> str:
    if np.isnan(months):
        return NO_BREAK
    for lo, hi, label in RECOVERY_BUCKETS:
        if lo <= months < hi:
            return label
    return RECOVERY_BUCKETS[-1][2]


def add_recovery(errors: pd.DataFrame, breaks=BREAKS) -> pd.DataFrame:
    """Add ``last_break`` and ``since_break`` (bucket of months from that break to the origin)."""
    out = errors.copy()
    origins = pd.to_datetime(out["origin"]).dt.date
    cache = {o: months_since_break(o, breaks) for o in set(origins)}
    out["last_break"] = [cache[o][0] for o in origins]
    out["since_break"] = [recovery_bucket(cache[o][1]) for o in origins]
    return out
