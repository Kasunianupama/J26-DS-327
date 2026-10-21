"""T0 evaluation cells, not model features or statistically confirmed break dates.

Saved errors record the calibration source (k_source), which can be borrowed.
Use explicit origin_source when available, otherwise the documented source timeline;
never mistake a borrowed calibration source for the recording source at issuance.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SHIPMENT_SPLIT = pd.Timestamp("2020-08-01")
BREAK_START = pd.Timestamp("2022-08-01")
GAP_START = pd.Timestamp("2024-03-01")
RESUME = pd.Timestamp("2024-05-01")
SHIPMENT_EARLY = "shipment_before_2020_08"
SHIPMENT = "shipment_from_2020_08"
CROSS_BREAK = "cross_break_shipment_to_delpro"
DELPRO_EARLY = "delpro_2022_2024"
GAP = "delpro_gap"
DELPRO_LATE = "delpro_from_2024_05"
REGIME_ORDER = [SHIPMENT_EARLY, SHIPMENT, CROSS_BREAK, DELPRO_EARLY, GAP, DELPRO_LATE]


def assign_regime(period_start, source, origin=None, origin_source=None):
    """Source-pair cells; split shipment by issuance date (not future target date).

    Two-argument callers describe same-date periods. Reports always supply origin.
    Missing/invalid explicit source stays unknown, never inferred from a target.
    """
    d = pd.to_datetime(period_start)
    o = d if origin is None else pd.to_datetime(origin)
    src = source.astype("string").fillna("unknown")
    if origin_source is None:
        osrc = pd.Series(np.where(o < BREAK_START, "shipment", "delpro"), index=d.index)
        osrc = osrc.where(o.notna(), "unknown")
    else:
        osrc = origin_source.astype("string").fillna("unknown")
    shipment = (osrc == "shipment") & (src == "shipment")
    delpro = (osrc == "delpro") & (src == "delpro")
    conds = [shipment & (o < SHIPMENT_SPLIT), shipment & (o >= SHIPMENT_SPLIT),
             (osrc == "shipment") & (src == "delpro"),
             delpro & (d < GAP_START), delpro & (d >= GAP_START) & (d < RESUME),
             delpro & (d >= RESUME)]
    return pd.Series(np.select([c.to_numpy(dtype=bool) for c in conds], REGIME_ORDER,
                               default="other"), index=d.index)


def boundary_audit(daily, origins):
    """Aggregate detector evidence from strictly pre-origin daily herd inputs only.

    Caller supplies daily aggregates; no loading, database access or imputation here.
    Calendar cells remain descriptive even if no detector hit supports a boundary.
    """
    from .breaks import detect_breaks, latest_break
    rows = []
    for origin in pd.to_datetime(origins):
        past = daily.loc[pd.to_datetime(daily["date"]) < origin]
        breaks = detect_breaks(past) if len(past) else []
        last = latest_break(origin, breaks)
        rows.append(dict(origin=origin, n_days=len(past), n_breaks=len(breaks),
                         days_since_latest=(origin - pd.Timestamp(last)).days
                         if last is not None else np.nan))
    return pd.DataFrame(rows)
