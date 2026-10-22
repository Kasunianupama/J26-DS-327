"""Aggregate-only diagnostics for the individual-cow yield models (notebook 05).

Every function returns counts, sums, means, shares or percentages per segment. No cow
identifier, row or per-cow value leaves this module. Segments with fewer than
``MIN_CELL`` cow-days are suppressed (shown as ``suppressed``) so that small groups cannot
be traced back to individual animals.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_CELL = 20
_BLOCKED = {"animal", "cow_id", "animal_key"}


def _summarise(err: pd.DataFrame, by: str) -> pd.DataFrame:
    """Accuracy, bias and hit rates per segment from row-level absolute errors."""
    g = err.groupby(by, observed=True)
    out = pd.DataFrame({
        "cow_days": g.size(),
        "cows": g["animal"].nunique(),
        "mean_actual": g["actual"].mean(),
        "mean_prediction": g["prediction"].mean(),
        "actual_sum": g["actual"].sum(),
        "abs_error_sum": g["abs_error"].sum(),
        "error_sum": g["error"].sum(),
        "within_10": g["within_10"].mean(),
        "naive_abs_error_sum": g["naive_abs_error"].sum(),
    })
    out["accuracy_pct"] = 100 - 100 * out["abs_error_sum"] / out["actual_sum"]
    out["bias_pct"] = 100 * out["error_sum"] / out["actual_sum"]
    out["within_10pct"] = 100 * out["within_10"]
    out["persistence_accuracy_pct"] = 100 - 100 * out["naive_abs_error_sum"] / out["actual_sum"]
    out["status"] = np.where(out["cow_days"] >= MIN_CELL, "ok", "suppressed")
    cols = ["cow_days", "cows", "mean_actual", "mean_prediction", "accuracy_pct",
            "persistence_accuracy_pct", "bias_pct", "within_10pct"]
    out.loc[out["status"] == "suppressed", cols[1:]] = np.nan
    out = out[["status"] + cols].reset_index().rename(columns={by: "segment"})
    out.insert(0, "breakdown", by)
    assert not (_BLOCKED & set(out.columns))
    return out


def _bands(values: pd.Series, edges: list[float], labels: list[str]) -> pd.Series:
    return pd.cut(values, edges, labels=labels, right=True)


def error_breakdown(frame: pd.DataFrame, prediction: np.ndarray, block: str = "test",
                    naive: np.ndarray | None = None) -> pd.DataFrame:
    """Where the daily model misses: accuracy by segment for scoreable ``block`` rows.

    Segments: days since the cow's previous record, whether that record is from the same
    lactation, days in milk, parity, calendar year, how densely the cow was recorded in
    the 28 days before, and whether health/treatment history was available.
    """
    f = frame.copy()
    f["prediction"] = np.asarray(prediction, dtype=float)
    f["naive"] = (np.asarray(naive, dtype=float) if naive is not None
                  else f["yield_lag1"].fillna(f["prediction"]).to_numpy())
    f = f[(f["period"] == block) & f["score_eligible"].astype(bool)].copy()
    if f.empty:
        return pd.DataFrame()
    f["actual"] = f["litres"]
    f["error"] = f["prediction"] - f["actual"]
    f["abs_error"] = f["error"].abs()
    f["within_10"] = f["abs_error"] <= 0.1 * f["actual"]
    f["naive_abs_error"] = (f["naive"] - f["actual"]).abs()

    f["days_since_record_band"] = _bands(
        f["days_since_record"], [-np.inf, 1, 3, 7, 30, 365, np.inf],
        ["1 day", "2-3 days", "4-7 days", "8-30 days", "31-365 days", ">365 days"],
    ).cat.add_categories("no earlier record").fillna("no earlier record")
    f["previous_record"] = np.where(
        f["yield_lag1"].isna(), "none / previous lactation",
        "same lactation")
    f["dim_band"] = _bands(f["dim"], [0, 60, 150, 305, np.inf],
                           ["1-60", "61-150", "151-305", ">305"])
    f["parity"] = f["parity_group"].astype(str)
    f["year"] = f["date"].dt.year
    f["recording_density_28d"] = _bands(
        f.get("cow_records_28d", pd.Series(np.nan, index=f.index)),
        [-np.inf, 0, 3, 10, np.inf], ["0", "1-3", "4-10", ">10"],
    ).cat.add_categories("unknown").fillna("unknown")
    f["health_history"] = f.get("health_status", pd.Series("unknown", index=f.index))
    f["treatment_history"] = f.get("treatment_status", pd.Series("unknown", index=f.index))

    parts = [_summarise(f, by) for by in (
        "days_since_record_band", "previous_record", "dim_band", "parity", "year",
        "recording_density_28d", "health_history", "treatment_history")]
    out = pd.concat(parts, ignore_index=True)
    out["segment"] = out["segment"].astype(str)
    return out


def noise_floor(frame: pd.DataFrame, max_gap_days: int = 3) -> pd.DataFrame:
    """How much a cow's recorded yield changes between records 1..``max_gap_days`` apart.

    Uses consecutive records of the same cow in the same lactation. If two records two
    days apart already differ by a median of x%, no model predicting a single cow-day can
    be expected to beat roughly that error. Reported per year (aggregate only).
    """
    f = frame.sort_values(["animal", "date"]).copy()
    prev_y = f.groupby("animal", sort=False)["litres"].shift(1)
    prev_d = f.groupby("animal", sort=False)["date"].shift(1)
    gap = (f["date"] - prev_d).dt.days
    same_lactation = f["dim"] > gap
    ok = prev_y.notna() & gap.between(1, max_gap_days) & same_lactation
    q = pd.DataFrame({"year": f.loc[ok, "date"].dt.year,
                      "abs_change": (f.loc[ok, "litres"] - prev_y[ok]).abs(),
                      "litres": f.loc[ok, "litres"]})
    q["rel_change"] = q["abs_change"] / q["litres"]
    rows = []
    for year, part in list(q.groupby("year")) + [("all", q)]:
        n = len(part)
        rows.append({
            "year": year, "record_pairs": n,
            "median_change_pct": 100 * part["rel_change"].median() if n else np.nan,
            "pairs_within_10pct": 100 * (part["rel_change"] <= 0.10).mean() if n else np.nan,
            # Accuracy of "same as a record 1-3 days earlier" on these pairs: an
            # empirical ceiling for single cow-day prediction from recent history.
            "short_gap_persistence_accuracy_pct":
                100 - 100 * part["abs_change"].sum() / part["litres"].sum() if n else np.nan,
            "status": "ok" if n >= MIN_CELL else "suppressed",
        })
    out = pd.DataFrame(rows)
    out.loc[out["status"] == "suppressed",
            ["median_change_pct", "pairs_within_10pct",
             "short_gap_persistence_accuracy_pct"]] = np.nan
    return out


def herd_level_accuracy(frames: dict[str, dict[str, pd.DataFrame]],
                        block: str = "test") -> pd.DataFrame:
    """Accuracy of the herd's mean yield per recorded cow-day (errors may cancel here)."""
    rows = []
    for model, grains in frames.items():
        for grain, f in grains.items():
            q = f[f["period"] == block]
            if q.empty:
                continue
            w = q["cow_days"]
            err = (q["prediction"] - q["actual"]).abs()
            rows.append({
                "model": model, "grain": grain, "periods": len(q),
                "herd_accuracy_pct": 100 - 100 * float((err * w).sum() / (q["actual"] * w).sum()),
                "herd_periods_within_5pct": 100 * float((err <= 0.05 * q["actual"]).mean()),
                "herd_periods_within_10pct": 100 * float((err <= 0.10 * q["actual"]).mean()),
                "herd_bias_pct": 100 * float(((q["prediction"] - q["actual"]) * w).sum()
                                             / (q["actual"] * w).sum()),
            })
    return pd.DataFrame(rows)


def sensor_scale_by_year(raw: pd.DataFrame,
                         columns: tuple[str, ...] = ("milkings", "conductivity",
                                                     "milking_duration_sec", "avg_blood",
                                                     "thi_mean")) -> pd.DataFrame:
    """Per-year mean, median, zero share and non-null count of each sensor (aggregate)."""
    f = raw.assign(year=pd.to_datetime(raw["date"]).dt.year)
    rows = []
    for column in columns:
        if column not in f:
            continue
        x = pd.to_numeric(f[column], errors="coerce")
        for year, part in x.groupby(f["year"]):
            n = int(part.notna().sum())
            rows.append({"sensor": column, "year": int(year), "non_null": n,
                         "mean": part.mean() if n else np.nan,
                         "median": part.median() if n else np.nan,
                         "zero_pct": 100 * float((part == 0).sum() / n) if n else np.nan})
    return pd.DataFrame(rows)


FORBIDDEN_MILK_FIELDS = ("milk_shipped", "milk_internal", "milk_hand_milked_est",
                         "milk_delpro", "herd_milk_measured",
                         "milk_observed_placeholder_litres")


def cleaning_contract_checks(raw: pd.DataFrame, target_sql: str, start, end) -> pd.DataFrame:
    """The notebook-05 data-cleaning contract as a PASS/FAIL table (aggregate evidence)."""
    litres = pd.to_numeric(raw["litres"], errors="coerce")
    dates = pd.to_datetime(raw["date"], errors="coerce")
    duplicates = int(raw.duplicated(["cow_id", "date"], keep=False).sum())
    outside_range = int((litres.isna() | ~litres.gt(0) | ~litres.le(18.0)).sum())
    outside_dates = int((dates.isna() | dates.lt(pd.Timestamp(start))
                         | dates.gt(pd.Timestamp(end))).sum())
    forbidden = sorted(set(raw.columns) & ({"animal_key", "record_key", "group_key"}
                                           | set(FORBIDDEN_MILK_FIELDS)))
    rows = [
        ("target source is core.animal_daily", "FROM core.animal_daily" in target_sql,
         "required source clause present"),
        ("shipment/history/placeholder-total fields are absent",
         not any(name in target_sql for name in FORBIDDEN_MILK_FIELDS),
         "0 forbidden target fields referenced"),
        ("placeholder animals are excluded",
         "d.animal_key <> 'A_PLACEHOLDER'" in target_sql
         and "NOT COALESCE(a.is_placeholder, false)" in target_sql,
         "both placeholder predicates present"),
        ("invalid, bad-date and unlinked records are excluded",
         "d.is_yield_valid" in target_sql and "NOT COALESCE(d.is_bad_date, false)" in target_sql
         and "NOT COALESCE(d.is_unlinked_animal, false)" in target_sql,
         "all three validity predicates present"),
        ("yield is restricted to (0, 18] litres", outside_range == 0,
         f"out-of-range rows after loading: {outside_range:,}"),
        ("one row per cow and date", duplicates == 0,
         f"duplicate cow-day rows after loading: {duplicates:,}"),
        ("dates are inside the declared experiment", outside_dates == 0,
         f"out-of-window or invalid dates: {outside_dates:,}"),
        ("restricted source keys and forbidden milk fields are not retained",
         len(forbidden) == 0, f"forbidden loaded columns: {len(forbidden)}"),
    ]
    out = pd.DataFrame(rows, columns=["check", "passed", "aggregate_evidence"])
    out.insert(0, "status", np.where(out["passed"], "PASS", "FAIL"))
    return out


def period_cleaning_checks(performance: dict[str, dict[str, pd.DataFrame]]) -> pd.DataFrame:
    """Weekly/monthly public frames must be complete periods of mean cow-day yield."""
    rows = []
    for model, grains in performance.items():
        for grain, frame in grains.items():
            if grain not in {"weekly", "monthly"} or frame.empty:
                continue
            min_coverage = float(frame["coverage"].min())
            passed = min_coverage == 1.0 and bool(frame["actual"].gt(0).all())
            rows.append({"model": model, "grain": grain,
                         "status": "PASS" if passed else "FAIL", "periods": len(frame),
                         "minimum_day_coverage": min_coverage,
                         "mean_cow_period_litres_min": float(frame["actual"].min()),
                         "mean_cow_period_litres_max": float(frame["actual"].max()),
                         "passed": passed})
    return pd.DataFrame(rows)


def record_consistency(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Is the day-to-day noise real yield variation or partial/odd records? (aggregate)

    ``ratio_bands``: each record divided by the median of the cow's previous 5 records in
    the same lactation, binned per year. A real cow rarely gives < 60% or > 150% of her
    recent median; a large share there points to partial or mis-assigned records.
    ``by_milkings``: cow-days and mean litres by recorded milkings per day.
    ``by_weekday``: cow-days and mean litres by day of week (a recording-routine effect).
    """
    f = frame.sort_values(["animal", "date"]).copy()
    key = [f["animal"], f["lactation"]] if "lactation" in f else [f["animal"]]
    prev_median = (f.groupby(key, sort=False)["litres"]
                   .transform(lambda s: s.shift(1).rolling(5, min_periods=3).median()))
    ratio = f["litres"] / prev_median
    bands = pd.cut(ratio, [0, 0.6, 0.8, 1.2, 1.5, np.inf],
                   labels=["<0.6", "0.6-0.8", "0.8-1.2", "1.2-1.5", ">1.5"])
    year = f["date"].dt.year
    q = pd.DataFrame({"year": year, "band": bands}).dropna()
    ratio_tbl = (pd.crosstab(q["year"], q["band"], normalize="index") * 100).round(1)
    ratio_tbl["records_with_history"] = q.groupby("year").size()
    out = {"ratio_bands": ratio_tbl.reset_index()}
    if "milkings" in f:
        m = pd.to_numeric(f["milkings"], errors="coerce")
        g = f.assign(milkings=m.fillna(-1)).groupby([year.rename("year"), "milkings"])
        tbl = g["litres"].agg(cow_days="size", mean_litres="mean").reset_index()
        tbl["milkings"] = tbl["milkings"].replace(-1, np.nan)
        out["by_milkings"] = tbl[tbl["cow_days"] >= MIN_CELL]
    wd = f.groupby([year.rename("year"), f["date"].dt.day_name().rename("weekday")])
    tbl = wd["litres"].agg(cow_days="size", mean_litres="mean").reset_index()
    out["by_weekday"] = tbl[tbl["cow_days"] >= MIN_CELL]
    for t in out.values():
        assert not (_BLOCKED & set(t.columns))
    return out
