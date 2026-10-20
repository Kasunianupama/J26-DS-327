"""Milk-record status at a forecast date (M1/M3/M4, page banner F1; docs/pp1_plan.md).

Four checks on the herd-level daily target before the forecast date, all known at that
date: freshness (days since the last trusted milk day), completeness (trusted days in the
last 28), plausibility (litres per recorded milking cow-day, at most 20 L by the user's farm
knowledge) and source agreement (share of DelPro milk tied to a cow). Herd level only.

The status words are display rules, not model results:
* ``current``: a trusted day within the last ``CURRENT_DAYS`` days and plausible records;
* ``stale``: older records, or records that fail a check; ranges are widened (M4);
* ``withheld``: no trusted milk level at all; the milk forecast is withheld (M1).
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from .episodes import MAX_LITRES_PER_COW_DAY, VERIFIED_MIN_SHARE

LOOKBACK_DAYS = 28
CURRENT_DAYS = 3  # display rule: daily records are normally at most a few days behind
REASON_TEXT = {
    "milk_withheld:no_trusted_recent_days":
        "No trusted milk records in the last 28 days and no earlier calibration, "
        "so no milk forecast is given. Herd numbers are still forecast.",
}


def _check(name: str, ok: bool | None, value, detail: str) -> dict:
    return {"check": name, "ok": ok, "value": value, "detail": detail}


def record_status(target: pd.DataFrame, panel: pd.DataFrame | None, origin: date,
                  milk_withheld: str | None = None) -> dict:
    """Status of the milk records before ``origin`` (aggregates only)."""
    t = target.copy()
    t["date"] = pd.to_datetime(t["date"]).dt.date
    t = t[t["date"] < origin]
    ok = t["is_scoreable"].fillna(False).astype(bool) & t["target_litres"].notna()
    last = max(t.loc[ok, "date"]) if ok.any() else None
    stale = (origin - last).days if last else None
    recent = t[t["date"] >= origin - timedelta(days=LOOKBACK_DAYS)]
    rok = ok.loc[recent.index]
    fresh = int(rok.sum())

    checks = [
        _check("freshness", stale is not None and stale <= CURRENT_DAYS, stale,
               "days since the last trusted milk day" if stale is not None else "no trusted milk day"),
        _check("completeness", fresh >= LOOKBACK_DAYS // 2, fresh,
               f"trusted milk days in the last {LOOKBACK_DAYS}"),
    ]
    lpc = None
    if panel is not None and len(panel) and fresh:
        p = panel.copy()
        p["date"] = pd.to_datetime(p["date"]).dt.date
        m = recent[rok].merge(p[["date", "milking"]], on="date", how="left")
        cows = float(m["milking"].sum())
        lpc = round(float(m["target_litres"].sum()) / cows, 2) if cows > 0 else None
    checks.append(_check("plausibility", None if lpc is None else lpc <= MAX_LITRES_PER_COW_DAY, lpc,
                         f"litres per recorded milking cow-day (at most {MAX_LITRES_PER_COW_DAY:g})"))
    share = None
    if "identified_share" in recent and "target_source" in recent:
        d = recent[rok & (recent["target_source"] == "delpro")]
        if len(d) and d["identified_share"].notna().any():
            share = round(float(d["identified_share"].mean()), 3)
    checks.append(_check("source_agreement", None if share is None else share >= VERIFIED_MIN_SHARE,
                         share, "share of DelPro milk tied to a cow"))

    if milk_withheld:
        status = "withheld"
    elif all(c["ok"] is not False for c in checks):
        status = "current"
    else:
        status = "stale"
    return {
        "status": status,
        "last_trusted_day": last.isoformat() if last else None,
        "staleness_days": stale,
        "fresh_days": fresh,
        "lookback_days": LOOKBACK_DAYS,
        "checks": checks,
        "milk_withheld": bool(milk_withheld),
        "reason": milk_withheld,
        "reason_text": REASON_TEXT.get(milk_withheld or "", None),
        "rule": "display rule (docs/pp1_plan.md): current = trusted day within "
                f"{CURRENT_DAYS} days and no failed check",
    }


def staleness_days(target: pd.DataFrame, origin: date) -> float:
    s = record_status(target, None, origin)["staleness_days"]
    return float(s) if s is not None else np.nan
