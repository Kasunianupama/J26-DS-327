"""Why is a compare-runs milk panel empty? Counts from built page documents only.

The milk panel draws three things from each document: the milk forecasts (``outlook``),
the recorded history before the date (``actuals``, scoreable only) and the recorded
outcome after it (``realised``, scoreable only). This prints, per version, origin and
grain, how many of each exist, plus withheld reasons and the record status: all counts,
no values. Cow-correction artifacts (pfoi-1.7.0-dev) are summarised by their number of
herd-days.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .compare_runs import HISTORY_DAYS

GRAINS = ("day", "week", "month")


def _milk(frame: pd.DataFrame, grain: str) -> pd.DataFrame:
    if not len(frame) or not {"grain", "series"} <= set(frame.columns):
        return frame.iloc[0:0]
    return frame[(frame["grain"] == grain) & (frame["series"] == "milk_litres")]


def document_counts(doc: dict, origin: date, version: str) -> list[dict]:
    rows = []
    out = pd.DataFrame(doc.get("outlook", []))
    act = pd.DataFrame(doc.get("actuals", []))
    real = pd.DataFrame(doc.get("realised", []))
    status = (doc.get("record_status") or {}).get("status")
    reasons = sorted({w.get("reason") for w in doc.get("withheld") or []
                      if w.get("series") == "milk_litres"})
    for g in GRAINS:
        o = _milk(out, g)
        fin = pd.to_numeric(o["forecast"], errors="coerce").notna().sum() if len(o) else 0
        a = _milk(act, g)
        if len(a):
            start = origin - timedelta(days=HISTORY_DAYS[g])
            a = a[pd.to_datetime(a["period"]).dt.date >= start]
        r = _milk(real, g)

        def scoreable(f):
            return int((f["scoreable"].astype(bool) & f["value"].notna()).sum()) if len(f) else 0

        rows.append({"version": version, "origin": origin.isoformat(), "grain": g,
                     "milk_forecasts": int(len(o)), "finite_forecasts": int(fin),
                     "history_periods": int(len(a)), "history_scoreable": scoreable(a),
                     "outcome_periods": int(len(r)), "outcome_scoreable": scoreable(r),
                     "record_status": status, "milk_withheld_reasons": ";".join(reasons) or "-"})
    return rows


def check(out_dir, versions: list[str], origins: list[str], artifacts=None) -> pd.DataFrame:
    root = Path(out_dir) / "outlook"
    rows = []
    for v in versions:
        for o in origins:
            origin = date.fromisoformat(o)
            p = root / v / f"run_{origin:%Y%m}.json"
            if not p.is_file():
                rows.append({"version": v, "origin": o, "grain": "-", "milk_forecasts": None,
                             "milk_withheld_reasons": "document missing"})
                continue
            rows += document_counts(json.loads(p.read_text()), origin, v)
    table = pd.DataFrame(rows)
    if artifacts:
        art = []
        for o in origins:
            f = Path(artifacts) / f"cow_correction_{date.fromisoformat(o):%Y%m}.json"
            if f.is_file():
                a = json.loads(f.read_text())
                art.append({"origin": o, "artifact_herd_days": len(a.get("daily") or []),
                            "calibration_cells": len(a.get("calibration") or [])})
            else:
                art.append({"origin": o, "artifact_herd_days": None, "calibration_cells": None})
        table.attrs["artifacts"] = pd.DataFrame(art)
    return table
