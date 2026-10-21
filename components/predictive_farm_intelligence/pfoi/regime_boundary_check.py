"""USER-RUN ONLY: aggregate T0 boundary audit; never run by an AI on real data.

Reads daily herd aggregates locally, prints only counts and elapsed days.
No files are written. Detector dates are evidence, not tuned regime definitions.
"""
from datetime import date

import pandas as pd

from .regime_cells import boundary_audit

ORIGINS = ["2020-08-01", "2020-09-01", "2022-08-01", "2022-09-01",
           "2024-03-01", "2024-05-01", "2024-06-01"]


def audit_source(source):
    start, end = date(2015, 8, 1), date(2024, 6, 1)
    panel = source.panel_daily(start, end)[["date", "n_herd"]]
    target = source.target_daily(start, end)[["date", "is_scoreable", "target_litres"]]
    daily = panel.merge(target, on="date", how="outer", validate="one_to_one")
    result = boundary_audit(daily, ORIGINS)
    result["use"] = result.origin.map(
        lambda o: "development" if o < pd.Timestamp("2024-01-01") else "posthoc_descriptive")
    return result


def main():
    # Deliberately lazy: tests call audit_source with a synthetic source only.
    from .data import SqlHerdSource
    result = audit_source(SqlHerdSource.from_env())
    print("Calendar boundaries are descriptive; no detector hit is also a valid result.")
    print("Only days strictly before each audit origin reach breaks.detect_breaks.")
    print(result.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
