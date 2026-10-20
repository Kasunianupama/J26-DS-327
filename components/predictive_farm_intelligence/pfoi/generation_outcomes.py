"""Separate outcomes by generation (M8, docs/pp1_plan.md). Descriptive only.

Generation = farm-born generations in the maternal line (not breed, not genetics).
Generations differ in age, parity and calendar period, so every comparison is made within
calving period, and yield is compared within parity x lactation stage x heat band
(indirect standardisation). Outcomes are kept separate; there is no single efficiency score,
and no feed efficiency (there are no intake records).

* ``yield_vs_expected``: observed reliable cow-day yield / the yield expected if the
  generation had the period's average yield in each of its parity x stage x heat strata;
* ``yield_record_coverage``: reliable cow-day records per milking cow-day (how much of the
  generation's milking is measured at all; low coverage = weak yield evidence);
* ``productive_share``: milking days / (milking + dry) days of calved cows;
* reproductive timing from ``repro_timing`` (days to first recorded service and to known
  conception; share of pregnancies with a known outcome that calved, and the share still
  pending), with censoring and competing exits;
* ``alarm_share`` / ``persistent_alarm_share``: sensor era only; signals, not diagnoses.

Every row carries ``n`` (cow-days or lactations). Associations, never causes.
"""
from __future__ import annotations

import pandas as pd

from .repro_timing import repro_table

STRATA = ["parity_group", "dim_band", "heat_band"]
NOTE = ("Associations within calving period only; generation is confounded with age, "
        "parity and time. Not genetic or causal effects.")


def yield_vs_expected(y: pd.DataFrame) -> pd.DataFrame:
    """Indirectly standardised yield ratio per period x generation."""
    if not len(y):
        return pd.DataFrame(columns=["period", "generation_group", "outcome", "value", "n"])
    ref = y.groupby(["period"] + STRATA)[["litres", "cow_days"]].sum()
    ref = (ref["litres"] / ref["cow_days"]).rename("ref_mean").reset_index()
    m = y.merge(ref, on=["period"] + STRATA)
    m["expected"] = m["cow_days"] * m["ref_mean"]
    g = m.groupby(["period", "generation_group"])[["litres", "expected", "cow_days"]].sum().reset_index()
    return pd.DataFrame({"period": g["period"], "generation_group": g["generation_group"],
                         "outcome": "yield_vs_expected", "value": g["litres"] / g["expected"],
                         "n": g["cow_days"]})


def time_and_coverage(days: pd.DataFrame, y: pd.DataFrame) -> pd.DataFrame:
    """Productive share of calved cows' days and yield-record coverage per period x generation."""
    rows = []
    cows = days[days["parity_group"].astype(str) != "0"]
    piv = cows.pivot_table(index=["period", "generation_group"], columns="state",
                           values="animal_days", aggfunc="sum", fill_value=0.0)
    for col in ("milking", "dry_open", "dry_pregnant"):
        if col not in piv:
            piv[col] = 0.0
    dry = piv["dry_open"] + piv["dry_pregnant"]
    for (period, gen), r in piv.iterrows():
        tot = r["milking"] + dry.loc[(period, gen)]
        if tot > 0:
            rows.append((period, gen, "productive_share", r["milking"] / tot, tot))
    rec = y.groupby(["period", "generation_group"])["cow_days"].sum() if len(y) else pd.Series(dtype=float)
    for (period, gen), r in piv.iterrows():
        if r["milking"] > 0:
            rows.append((period, gen, "yield_record_coverage",
                         float(rec.get((period, gen), 0.0)) / r["milking"], r["milking"]))
    return pd.DataFrame(rows, columns=["period", "generation_group", "outcome", "value", "n"])


def repro_outcomes(steps: pd.DataFrame) -> pd.DataFrame:
    rows = []
    t = repro_table(steps, ("period", "generation_group"))
    for r in t.to_dict("records"):
        if r["step"] == "first_ai" and r.get("median_days") is not None:
            rows.append((r["period"], r["generation_group"], "days_to_first_service_median",
                         r["median_days"], r["n"]))
        if r["step"] == "conception":
            if r.get("median_days") is not None:
                rows.append((r["period"], r["generation_group"], "days_to_conception_median",
                             r["median_days"], r["n"]))
            rows.append((r["period"], r["generation_group"], "conceived_by_150d", r["by_150d"], r["n"]))
        if r["step"] == "pregnancy" and r.get("calved_of_resolved") is not None:
            # over pregnancies with a known outcome; still-pregnant ones are not failures
            rows.append((r["period"], r["generation_group"], "pregnancy_calved_share",
                         r["calved_of_resolved"], r["n_resolved"]))
            rows.append((r["period"], r["generation_group"], "pregnancy_pending_share",
                         r["censored_share"], r["n"]))
    return pd.DataFrame(rows, columns=["period", "generation_group", "outcome", "value", "n"])


def alarm_outcomes(a: pd.DataFrame) -> pd.DataFrame:
    if not len(a):
        return pd.DataFrame(columns=["period", "generation_group", "outcome", "value", "n"])
    rows = []
    for r in a.itertuples():
        if r.cow_days > 0:
            rows.append((r.period, r.generation_group, "alarm_share", r.alarm_cow_days / r.cow_days, r.cow_days))
            rows.append((r.period, r.generation_group, "persistent_alarm_share",
                         r.persistent_cow_days / r.cow_days, r.cow_days))
    return pd.DataFrame(rows, columns=["period", "generation_group", "outcome", "value", "n"])


def generation_outcomes(yield_strata: pd.DataFrame, days: pd.DataFrame, steps: pd.DataFrame,
                        alarms: pd.DataFrame | None = None) -> pd.DataFrame:
    """All outcomes in one long table: period, generation_group, outcome, value, n."""
    parts = [yield_vs_expected(yield_strata), time_and_coverage(days, yield_strata),
             repro_outcomes(steps)]
    if alarms is not None:
        parts.append(alarm_outcomes(alarms))
    out = pd.concat([p for p in parts if len(p)], ignore_index=True)
    out = out[out["generation_group"] != "unknown"]
    return out.sort_values(["outcome", "period", "generation_group"]).reset_index(drop=True)
