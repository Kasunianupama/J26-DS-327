"""Leakage-resistant chronological individual-cow milk-yield comparison.

The experiment is intentionally separate from the published PFOI forecast. It selects
models with the second half of 2019, refits through 2019 and evaluates unseen 2020--2026
observations. Cow identifiers
are replaced inside SQL by a per-run integer and are used only for fitting random effects
and lag features. Public results are aggregate daily, weekly and monthly diagnostics.

Holdout features are frozen at the training cut-off. Later holdout outcomes never update
lags, parity or lactation stage. Only cows known at the cut-off are scoreable. Metrics are
calculated on cow-period errors before any public aggregation, so errors from different
cows cannot cancel. This module does not claim to forecast herd totals: that requires the
separate herd engine to project the future milking population.

The target is a unique, valid ``core.animal_daily`` cow record in (0, 18] litres.  Herd
placeholder, unlinked, bad-date and duplicate cow-day records never become targets.
``core.daily_milk`` sensors enter only as the cow's previous-record value. Health episodes
and treatments (``pfoi.cow_events``) are counted strictly before the observation date, and
years in which a source has no records are encoded as ``unavailable``, never as zero events.
"""
from __future__ import annotations

import contextlib
import io
import os
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .cow_events import (DEFAULT_MIN_RECORDS, add_event_features, feature_family,
                         load_event_inputs)
from .cow_layer import CowSplit, fit_ebm, fit_wood_mixed, prepare_cowdays
from .data import _IDENT

TRAIN_START = date(2015, 8, 1)
SELECTION_TRAIN_END = date(2019, 6, 30)
VALID_START = date(2019, 7, 1)
VALID_END = date(2019, 12, 31)
FINAL_TRAIN_END = VALID_END
TRAIN_END = FINAL_TRAIN_END  # public compatibility: final refit uses all development data
TEST_START = date(2020, 1, 1)
TEST_END = date(2026, 8, 31)
MAX_LITRES = 18.0
MIN_COWS_PER_DAY = 10
# model_input2 requires weekly/monthly values to be built only from complete
# clean-daily periods. Partial periods must remain gaps, never partial "totals".
MIN_PERIOD_COVERAGE = 1.0
MIN_ORIGIN_HISTORY = 3
EXPERIMENT_VERSION = "cow-accuracy-v10"  # printed by notebook 05 to catch a stale kernel
# Candidate name of this individual-cow yield model and of its test protocol. It is a
# development candidate only: nothing is written to c1_output until the user decides.
COW_MODEL_VERSION = "pfoi-1.6.0-dev"
COW_MODEL_NAME = "pfoi-cow-yield-1.6.0-dev"
COW_TEST_NAME = "cow-yield-test-clean-75-5-20"  # gap excluded, 75/5/20 cow-day split
# Cow records from May 2022 to October 2025 are sparse fragments with implausibly low
# yields (a recording gap); they are excluded by default. Clean recording resumes on
# 2025-11-01 (user decision, 2026-10-22).
RECORDING_GAP = (date(2022, 5, 1), date(2025, 10, 31))
# Data scopes: which period is removed before the 75/5/20 split.
#   clean          - the whole recording gap above (default)
#   through_mid2023 - keep the May 2022 - June 2023 records; drop only July 2023 -
#                     October 2025, where records are too few to train or score on
DATA_SCOPES = {
    "clean": RECORDING_GAP,
    "through_mid2023": (date(2023, 7, 1), date(2025, 10, 31)),
}
SCOPE_TEST_NAMES = {
    "clean": "cow-yield-test-clean-75-5-20",
    "through_mid2023": "cow-yield-test-through-mid2023-75-5-20",
}
SPLIT_SHARES = (0.75, 0.05, 0.20)  # train, validation, test share of clean cow-days


def cpu_cores(n_jobs: int | None = -1) -> int:
    """Number of CPU worker threads/processes: -1 or None means every core."""
    total = os.cpu_count() or 1
    if n_jobs is None or n_jobs < 0:
        return total
    return max(1, min(int(n_jobs), total))
LEVEL_WINDOW_DAYS = 28
LEVEL_FEATURES = (
    "herd_resid_28d", "herd_yield_28d", "herd_cows_28d", "herd_level_available",
    "cow_resid_mean7", "cow_level_available", "cow_vs_herd_resid",
)

def cow_accuracy_sql(core: str) -> str:
    """One row per unique eligible ``animal_daily`` cow-day, without pseudonym keys."""
    if not _IDENT.match(core):
        raise ValueError(f"invalid schema name: {core!r}")
    return f"""
    WITH target_raw AS MATERIALIZED (
        SELECT d.animal_key, d.milk_date AS date,
               COUNT(*) AS n_records,
               MAX(d.yield_litres)::float AS litres,
               MAX(d.dim)::float AS dim,
               MAX(d.lactation_no)::float AS lactation_no
        FROM {core}.animal_daily d
        JOIN {core}.animal a ON a.animal_key = d.animal_key
        WHERE d.milk_date BETWEEN CAST(:start AS date) AND CAST(:end AS date)
          AND d.is_yield_valid
          AND NOT COALESCE(d.is_bad_date, false)
          AND NOT COALESCE(d.is_unlinked_animal, false)
          AND NOT COALESCE(a.is_placeholder, false)
          AND d.animal_key <> 'A_PLACEHOLDER'
          AND d.yield_litres > 0 AND d.yield_litres <= 18
        GROUP BY d.animal_key, d.milk_date
    ), target AS MATERIALIZED (
        SELECT * FROM target_raw WHERE n_records = 1
    ), milk_features AS MATERIALIZED (
        SELECT DISTINCT ON (d.animal_key, d.milk_date)
               d.animal_key, d.milk_date AS date,
               CASE WHEN d.milkings >= 0 THEN d.milkings::float END AS milkings,
               d.conductivity::float AS conductivity,
               CASE WHEN d.milking_duration_in_sec >= 0
                    THEN d.milking_duration_in_sec::float END AS milking_duration_sec,
               CASE WHEN d.avg_blood >= 0 THEN d.avg_blood::float END AS avg_blood,
               CASE WHEN d.avg_cell_count >= 0 THEN d.avg_cell_count::float END AS avg_cell_count,
               CASE WHEN d.avg_bcs BETWEEN 1 AND 5 THEN d.avg_bcs::float END AS avg_bcs,
               CASE WHEN d.avg_weight > 0 THEN d.avg_weight::float END AS avg_weight,
               d.avg_rectal_temp::float AS avg_rectal_temp
        FROM {core}.daily_milk d
        WHERE d.milk_date BETWEEN CAST(:start AS date) AND CAST(:end AS date)
          AND NOT COALESCE(d.is_bad_date, false)
          AND NOT COALESCE(d.is_unlinked_animal, false)
          AND NOT COALESCE(d.is_placeholder, false)
        ORDER BY d.animal_key, d.milk_date, d.milk_ts DESC NULLS LAST
    )
    SELECT DENSE_RANK() OVER (ORDER BY t.animal_key) AS cow_id,
           t.date, t.litres, t.dim,
           CASE WHEN t.lactation_no = 1 THEN '1'
                WHEN t.lactation_no = 2 THEN '2'
                WHEN t.lactation_no >= 3 THEN '3+' ELSE 'unknown' END AS parity_group,
           CASE WHEN a.birth_date IS NOT NULL THEN t.date - a.birth_date END AS age_days,
           mf.milkings, mf.conductivity, mf.milking_duration_sec, mf.avg_blood,
           mf.avg_cell_count, mf.avg_bcs, mf.avg_weight, mf.avg_rectal_temp,
           w.thi_mean::float AS thi_mean
    FROM target t
    JOIN {core}.animal a ON a.animal_key = t.animal_key
    LEFT JOIN milk_features mf ON mf.animal_key = t.animal_key AND mf.date = t.date
    LEFT JOIN {core}.weather_day w ON w.date = t.date
    ORDER BY t.date, cow_id"""


RAW_COLUMNS = (
    "cow_id", "date", "litres", "dim", "parity_group", "age_days", "milkings",
    "conductivity", "milking_duration_sec", "avg_blood", "avg_cell_count", "avg_bcs",
    "avg_weight", "avg_rectal_temp", "thi_mean",
)


def load_accuracy_cowdays(source, start: date = TRAIN_START,
                          end: date = TEST_END) -> pd.DataFrame:
    """Load the restricted in-memory modelling frame through a read-only source."""
    raw = source._q(cow_accuracy_sql(source.core), start=start, end=end)
    if "animal_key" in raw.columns:
        raise ValueError("cow accuracy frame must not contain animal_key")
    missing = set(RAW_COLUMNS) - set(raw.columns)
    if missing:
        raise ValueError(f"cow accuracy query missing columns: {sorted(missing)}")
    return raw[list(RAW_COLUMNS)].copy()


def load_accuracy_inputs(source, start: date = TRAIN_START, end: date = TEST_END) -> dict:
    """Cow-days plus health events, treatment events and yearly source availability."""
    health, treatments, availability = load_event_inputs(source, start, end)
    return {"raw": load_accuracy_cowdays(source, start, end), "health": health,
            "treatments": treatments, "availability": availability}


def recording_gap_check(raw: pd.DataFrame) -> pd.DataFrame:
    """Per-year cow-days, mean litres and mean recorded milkings (aggregate only)."""
    f = raw.assign(year=pd.to_datetime(raw["date"]).dt.year,
                   milkings=pd.to_numeric(raw.get("milkings"), errors="coerce"))
    out = f.groupby("year").agg(cow_days=("litres", "size"), cows=("cow_id", "nunique"),
                                mean_litres=("litres", "mean"),
                                mean_milkings=("milkings", "mean"),
                                milkings_recorded=("milkings", "count")).reset_index()
    out["in_recording_gap"] = out["year"].between(RECORDING_GAP[0].year,
                                                  RECORDING_GAP[1].year)
    return out


def exclude_recording_gap(raw: pd.DataFrame,
                          gap: tuple[date, date] | None = RECORDING_GAP) -> pd.DataFrame:
    """Drop cow-days inside the recording gap; they are neither trained on nor scored.

    Yield history from before the gap stays available to later forecasts (with a long
    ``days_since_record``), exactly as a real forecast would see it.
    """
    if gap is None:
        return raw.copy()
    d = pd.to_datetime(raw["date"])
    return raw[~d.between(pd.Timestamp(gap[0]), pd.Timestamp(gap[1]))].copy()


@dataclass
class SplitDates:
    train_end: date
    validation_end: date
    test_start: date
    summary: pd.DataFrame


def chronological_split(dates: pd.Series, shares: tuple[float, float, float] = SPLIT_SHARES,
                        test_end: date = TEST_END) -> SplitDates:
    """Cut dates so train/validation/test hold ``shares`` of cow-days, in time order.

    Cuts fall on whole days (a day is never split), so achieved shares differ slightly
    from the targets; ``summary`` reports both. No row is ever shuffled across time.
    """
    if not np.isclose(sum(shares), 1.0) or min(shares) <= 0:
        raise ValueError("shares must be positive and sum to 1")
    d = pd.to_datetime(pd.Series(dates)).dt.normalize()
    per_day = d.value_counts().sort_index()
    cum = per_day.cumsum() / per_day.sum()
    train_end = cum.index[max(int(np.searchsorted(cum.to_numpy(), shares[0], "right")) - 1, 0)]
    after_train = cum.index > train_end
    target = shares[0] + shares[1]
    idx = int(np.searchsorted(cum.to_numpy(), target, "right")) - 1
    validation_end = max(cum.index[idx], cum.index[after_train][0])
    test_days = cum.index[cum.index > validation_end]
    if not len(test_days):
        raise ValueError("no cow-days left for the test block")
    blocks = np.select([d <= train_end, d <= validation_end], ["train", "validation"], "test")
    summary = (pd.DataFrame({"block": blocks, "date": d}).groupby("block")
               .agg(start=("date", "min"), end=("date", "max"), cow_days=("date", "size"))
               .reindex(["train", "validation", "test"]).reset_index())
    summary["share_pct"] = 100 * summary["cow_days"] / summary["cow_days"].sum()
    summary["target_pct"] = [100 * x for x in shares]
    return SplitDates(train_end.date(), validation_end.date(),
                      (validation_end + pd.Timedelta(days=1)).date(), summary)


def prepare_accuracy_frame(raw: pd.DataFrame, train_end: date = FINAL_TRAIN_END,
                           validation_end: date = FINAL_TRAIN_END,
                           evaluation_mode: str = "fixed_origin",
                           events: dict | None = None,
                           min_source_records: int = DEFAULT_MIN_RECORDS,
                           origin_grain: str = "daily") -> pd.DataFrame:
    """Prepare origin-safe features for a chronological train/holdout experiment.

    Training rows use only earlier observations. ``fixed_origin`` freezes holdout history
    at ``train_end``. ``walk_forward`` permits only strictly earlier outcomes to inform a
    later one-day-ahead prediction while keeping model weights frozen.

    ``events`` (``health``, ``treatments``, ``availability`` frames) adds the origin-safe
    health, treatment, sensor-lag and THI-lag families; their model column names are kept
    in ``frame.attrs["event_features"]``.

    ``origin_grain`` (walk-forward only) sets the forecast issue date of each holdout row:
    ``daily`` = the row's own date (one day ahead); ``weekly``/``monthly`` = the first day
    of its Monday-start week or calendar month, so every feature for a day in that period
    uses only facts dated before the period began (a true 1-week / 1-month forecast).
    """
    if evaluation_mode not in {"fixed_origin", "walk_forward"}:
        raise ValueError("evaluation_mode must be fixed_origin or walk_forward")
    if origin_grain not in {"daily", "weekly", "monthly"}:
        raise ValueError("origin_grain must be daily, weekly or monthly")
    if {"animal_key", "record_key", "group_key"} & set(raw.columns):
        raise ValueError("source keys must not enter the modelling frame")
    f = raw.rename(columns={"cow_id": "animal"}).copy()
    # One datetime resolution everywhere: sources may return s, ms or ns precision, and
    # the as-of joins below require identical key types.
    f["date"] = pd.to_datetime(f["date"]).astype("datetime64[ns]")
    f["animal"] = pd.to_numeric(f["animal"], errors="raise").astype("int64")
    f["litres"] = pd.to_numeric(f["litres"], errors="coerce")
    f["dim"] = pd.to_numeric(f["dim"], errors="coerce")
    f["parity_group"] = f["parity_group"].astype(str)
    # ``is_future`` rows (production inference only) are cow-days to forecast after the
    # origin: no recorded litres, so they bypass the yield filter. Absent = Notebook 6.
    future = (f["is_future"].astype(bool) if "is_future" in f
              else pd.Series(False, index=f.index))
    if "is_future" in f:
        f["is_future"] = future
        if (future & f["litres"].notna()).any():
            raise ValueError("future cow-days must not carry recorded litres")
    f = f[(f["date"] >= pd.Timestamp(TRAIN_START))
          & ((f["date"] <= pd.Timestamp(TEST_END)) | future)]
    future = future.loc[f.index]
    f = f[((f["litres"] > 0) & (f["litres"] <= MAX_LITRES)) | future]
    if "milkings" in f:
        # 0 milkings on a day with recorded yield is impossible: in 2020 the source stores
        # 0 for "not recorded", so it is treated as missing, not as a real value.
        m = pd.to_numeric(f["milkings"], errors="coerce")
        f["milkings"] = m.where(m > 0)
    f = f.sort_values(["animal", "date"]).reset_index(drop=True)
    if f.duplicated(["animal", "date"]).any():
        raise ValueError("duplicate cow-days reached the accuracy model")

    if validation_end < train_end:
        raise ValueError("validation_end cannot precede train_end")
    f["period"] = np.select(
        [f["date"] <= pd.Timestamp(train_end),
         f["date"] <= pd.Timestamp(validation_end)],
        ["train", "validation"],
        default="test",
    )
    f["days_pregnant"] = 0.0  # no hindsight-derived conception date in this experiment
    f["after_dry_off"] = False

    # Training features use previous observations only.
    previous = f.groupby("animal", sort=False)["litres"].shift(1)
    f["yield_lag1"] = previous
    f["yield_mean7"] = previous.groupby(f["animal"], sort=False).transform(
        lambda s: s.rolling(7, min_periods=1).mean())
    f["yield_mean28"] = previous.groupby(f["animal"], sort=False).transform(
        lambda s: s.rolling(28, min_periods=2).mean())
    f["yield_sd28"] = previous.groupby(f["animal"], sort=False).transform(
        lambda s: s.rolling(28, min_periods=3).std())
    f["previous_date"] = f.groupby("animal", sort=False)["date"].shift(1)
    f["days_since_record"] = (f["date"] - f["previous_date"]).dt.days.astype(float)

    # Freeze every holdout cow at the training cut-off. In particular, neither H2 2019
    # validation outcomes nor 2020--2026 test outcomes may update later holdout features.
    history = f[f["date"] <= pd.Timestamp(train_end)].copy()
    anchor_rows = history.groupby("animal", sort=False).tail(1).set_index("animal")
    history_groups = history.groupby("animal", sort=False)["litres"]
    anchors = pd.DataFrame({
        "origin_history_n": history_groups.size(),
        "origin_yield_lag1": history_groups.last(),
        "origin_yield_mean7": history_groups.apply(lambda s: s.tail(7).mean()),
        "origin_yield_mean28": history_groups.apply(lambda s: s.tail(28).mean()),
        "origin_yield_sd28": history_groups.apply(lambda s: s.tail(28).std()),
    })
    anchors["origin_last_date"] = anchor_rows["date"]
    anchors["origin_dim"] = anchor_rows["dim"]
    anchors["origin_age_days"] = anchor_rows["age_days"]
    anchors["origin_parity_group"] = anchor_rows["parity_group"]

    holdout = f["date"] > pd.Timestamp(train_end)
    if evaluation_mode == "fixed_origin":
        animal = f.loc[holdout, "animal"]
        last_date = animal.map(anchors["origin_last_date"])
        elapsed = (f.loc[holdout, "date"] - last_date.to_numpy()).dt.days.astype(float)
        f.loc[holdout, "yield_lag1"] = animal.map(anchors["origin_yield_lag1"]).to_numpy()
        f.loc[holdout, "yield_mean7"] = animal.map(anchors["origin_yield_mean7"]).to_numpy()
        f.loc[holdout, "yield_mean28"] = animal.map(anchors["origin_yield_mean28"]).to_numpy()
        f.loc[holdout, "yield_sd28"] = animal.map(anchors["origin_yield_sd28"]).to_numpy()
        f.loc[holdout, "days_since_record"] = elapsed.to_numpy()
        f.loc[holdout, "dim"] = (
            animal.map(anchors["origin_dim"]).to_numpy(dtype=float) + elapsed.to_numpy()
        )
        f.loc[holdout, "age_days"] = (
            animal.map(anchors["origin_age_days"]).to_numpy(dtype=float) + elapsed.to_numpy()
        )
        f.loc[holdout, "parity_group"] = animal.map(
            anchors["origin_parity_group"]
        ).fillna("unknown").to_numpy()
        f["origin_history_n"] = f["animal"].map(
            anchors["origin_history_n"]
        ).fillna(0).astype(int)
    else:
        # Model weights stay frozen; only outcomes from strictly earlier dates become
        # available to the next one-day-ahead prediction.
        f["origin_history_n"] = f.groupby("animal", sort=False).cumcount()

    origins = f["date"].copy()
    if evaluation_mode == "fixed_origin":
        origins[holdout] = pd.Timestamp(train_end) + pd.Timedelta(days=1)
        for column in ("prev_lactation_mean", "lactation_history_n", "cow_records_28d",
                       "days_since_any_record"):
            f[column] = np.nan
    else:
        if origin_grain != "daily":
            # Training rows use the same origin rule, so each grain's model learns from
            # the history it will actually have when the forecast is issued.
            origins[:] = _period_start(f["date"], origin_grain)
        if "origin_override" in f:
            # Production / backtest future rows: one fixed forecast origin at any lead.
            override = pd.to_datetime(f["origin_override"])
            origins = origins.where(override.isna(), override)
        _history_at_origin(f, origins)
    f["origin_date"] = origins
    f["origin_grain"] = origin_grain if evaluation_mode == "walk_forward" else "fixed"
    f["evaluation_mode"] = evaluation_mode
    f["origin_known_cow"] = f["origin_history_n"] >= MIN_ORIGIN_HISTORY
    f["score_eligible"] = (
        (f["period"] != "train")
        & f["origin_known_cow"]
        & f["dim"].between(1, 400)
    )
    doy = f["date"].dt.dayofyear.to_numpy()
    f["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    f["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    f = f.drop(columns="previous_date")
    event_features: list[str] = []
    if events is not None:
        f, event_features = add_event_features(
            f, events.get("health"), events.get("treatments"), events.get("availability"),
            train_end=train_end, origins=f["origin_date"],
            min_records=min_source_records,
        )
    f.attrs["event_features"] = event_features
    return f


def _freeze_history_at_origin(f: pd.DataFrame, holdout: pd.Series,
                              origins: pd.Series) -> None:
    """Replace yield-history features of ``holdout`` rows by those known before the origin."""
    g = f.groupby("animal", sort=False)["litres"]
    hist = pd.DataFrame({
        "animal": f["animal"], "last_date": f["date"], "litres": f["litres"],
        "n": g.cumcount() + 1,
        "mean7": g.transform(lambda s: s.rolling(7, min_periods=1).mean()),
        "mean28": g.transform(lambda s: s.rolling(28, min_periods=2).mean()),
        "sd28": g.transform(lambda s: s.rolling(28, min_periods=3).std()),
    }).sort_values("last_date")
    left = pd.DataFrame({"row": f.index[holdout], "animal": f.loc[holdout, "animal"],
                         "origin": origins[holdout]}).sort_values("origin")
    m = pd.merge_asof(left, hist, left_on="origin", right_on="last_date", by="animal",
                      allow_exact_matches=False).set_index("row").reindex(f.index[holdout])
    f.loc[holdout, "yield_lag1"] = m["litres"].to_numpy()
    f.loc[holdout, "yield_mean7"] = m["mean7"].to_numpy()
    f.loc[holdout, "yield_mean28"] = m["mean28"].to_numpy()
    f.loc[holdout, "yield_sd28"] = m["sd28"].to_numpy()
    f.loc[holdout, "days_since_record"] = (
        f.loc[holdout, "date"] - m["last_date"].to_numpy()).dt.days.astype(float).to_numpy()
    f.loc[holdout, "origin_history_n"] = m["n"].fillna(0).astype(int).to_numpy()


HISTORY_CAP_DAYS = 400.0


def _lactation_ids(f: pd.DataFrame) -> pd.Series:
    """Number each cow's lactations from the records (sorted by cow and date).

    A record starts a new lactation when the cow has no earlier record, when its days in
    milk are not larger than the days since her previous record (she calved in between),
    or when her parity group changes. DIM and parity are operationally known on the day.
    """
    prev_date = f.groupby("animal", sort=False)["date"].shift(1)
    prev_parity = f.groupby("animal", sort=False)["parity_group"].shift(1)
    gap = (f["date"] - prev_date).dt.days
    new = prev_date.isna() | (f["dim"] <= gap) | (f["parity_group"] != prev_parity)
    return new.astype(int).groupby(f["animal"], sort=False).cumsum()


def _history_at_origin(f: pd.DataFrame, origins: pd.Series) -> None:
    """Yield-history features known strictly before each row's origin, per lactation.

    Lags (last yield, 7/28-record means, 28-record SD, days since that record) come only
    from earlier records of the *same* lactation as the predicted day; a yield from a
    previous lactation is not a lag. ``prev_lactation_mean`` gives the mean of the
    cow's most recent earlier lactation known at the origin instead. Also adds
    ``lactation_history_n`` (same-lactation records before the origin),
    ``cow_records_28d`` (records in the 28 days before the origin) and
    ``days_since_any_record``. Day counts are capped at ``HISTORY_CAP_DAYS``.
    """
    f["lactation"] = _lactation_ids(f)
    g = f.groupby(["animal", "lactation"], sort=False)["litres"]
    hist = pd.DataFrame({
        "animal": f["animal"], "last_date": f["date"], "last_lactation": f["lactation"],
        "litres": f["litres"],
        "n_lact": g.cumcount() + 1,
        "n_total": f.groupby("animal", sort=False).cumcount() + 1,
        "mean7": g.transform(lambda s: s.rolling(7, min_periods=1).mean()),
        "mean28": g.transform(lambda s: s.rolling(28, min_periods=2).mean()),
        "sd28": g.transform(lambda s: s.rolling(28, min_periods=3).std()),
        "lact_running_mean": g.transform(lambda s: s.expanding().mean()),
    }).sort_values("last_date")
    full_mean = f.groupby(["animal", "lactation"])["litres"].mean()

    left = pd.DataFrame({"row": np.arange(len(f)), "animal": f["animal"].to_numpy(),
                         "origin": pd.to_datetime(origins).to_numpy().astype("datetime64[ns]"),
                         "lactation": f["lactation"].to_numpy()}).sort_values("origin")
    m = pd.merge_asof(left, hist, left_on="origin", right_on="last_date", by="animal",
                      allow_exact_matches=False).sort_values("row").set_index("row")
    window_start = left.assign(origin=left["origin"] - pd.Timedelta(days=28))
    m28 = (pd.merge_asof(window_start.sort_values("origin"), hist[["animal", "last_date",
                                                                  "n_total"]],
                         left_on="origin", right_on="last_date", by="animal",
                         allow_exact_matches=False).sort_values("row").set_index("row"))

    same = (m["last_lactation"] == m["lactation"]).to_numpy()
    has_prev = m["last_date"].notna().to_numpy()
    date = f["date"].to_numpy()
    since_any = (date - m["last_date"].to_numpy()).astype("timedelta64[D]").astype(float)
    since_any[~has_prev] = np.nan
    f["yield_lag1"] = np.where(same, m["litres"], np.nan)
    f["yield_mean7"] = np.where(same, m["mean7"], np.nan)
    f["yield_mean28"] = np.where(same, m["mean28"], np.nan)
    f["yield_sd28"] = np.where(same, m["sd28"], np.nan)
    f["days_since_record"] = np.minimum(np.where(same, since_any, np.nan), HISTORY_CAP_DAYS)
    f["days_since_any_record"] = np.minimum(since_any, HISTORY_CAP_DAYS)
    f["lactation_history_n"] = np.where(same, m["n_lact"], 0).astype(float)
    # Previous lactation: when the last known record is from an earlier lactation, its
    # running mean; otherwise the full mean of lactation L-1 (all dated before L began).
    key = pd.MultiIndex.from_arrays([f["animal"], f["lactation"] - 1])
    prev_full = full_mean.reindex(key).to_numpy()
    f["prev_lactation_mean"] = np.where(same, prev_full,
                                        np.where(has_prev, m["lact_running_mean"], np.nan))
    n_before = m["n_total"].fillna(0).to_numpy()
    f["cow_records_28d"] = n_before - m28["n_total"].fillna(0).to_numpy()
    f["origin_history_n"] = n_before.astype(int)


BASE_FEATURES = (
    "dim", "age_days", "doy_sin", "doy_cos", "yield_lag1", "yield_mean7",
    "yield_mean28", "yield_sd28", "days_since_record", "days_since_any_record",
    "prev_lactation_mean", "lactation_history_n", "cow_records_28d",
)
EXCLUDED_SAME_DAY_FEATURES = (
    "milkings", "conductivity", "milking_duration_sec", "avg_blood", "avg_cell_count",
    "avg_bcs", "avg_weight", "avg_rectal_temp", "thi_mean",
)


def _design(f: pd.DataFrame, features: tuple[str, ...]) -> pd.DataFrame:
    x = f.reindex(columns=list(features)).apply(pd.to_numeric, errors="coerce")
    parity = pd.get_dummies(f["parity_group"], prefix="parity", dtype=float)
    for col in ("parity_1", "parity_2", "parity_3+", "parity_unknown"):
        if col not in parity:
            parity[col] = 0.0
    return pd.concat([x.reset_index(drop=True), parity.reset_index(drop=True)], axis=1)


def _add_level_features(f: pd.DataFrame, wood_pred: np.ndarray,
                        window: int = LEVEL_WINDOW_DAYS) -> pd.DataFrame:
    """Recent herd and cow yield level relative to the Wood curve, known at the origin.

    ``herd_resid_28d``: mean log(actual / Wood) over every recorded cow-day in the
    ``window`` days before the origin; ``herd_yield_28d``: mean litres in that window;
    ``cow_resid_mean7``: the cow's mean log(actual / Wood) over its last 7 records before
    the origin. Unavailable values are 0 with a 0/1 ``*_available`` flag, never null.
    These let a frozen model follow a herd-wide level shift (e.g. 2021-2023) that a
    calendar level fixed at the training cut-off cannot.
    """
    f = f.copy()
    resid = pd.Series(np.log(f["litres"].to_numpy() / np.maximum(wood_pred, 1e-6)),
                      index=f.index)
    day = f["date"].dt.normalize()
    origins = pd.DatetimeIndex(pd.to_datetime(f["origin_date"])).normalize()
    start = min(day.min(), origins.min()) - pd.Timedelta(days=window + 2)
    calendar = pd.date_range(start, day.max() + pd.Timedelta(days=1), freq="D")
    cum = (pd.DataFrame({"d": day, "r": resid, "y": f["litres"]}).groupby("d")
           .agg(r=("r", "sum"), y=("y", "sum"), n=("r", "size"))
           .reindex(calendar, fill_value=0).cumsum())
    hi = cum.reindex(origins - pd.Timedelta(days=1)).to_numpy()
    lo = cum.reindex(origins - pd.Timedelta(days=window + 1)).to_numpy()
    r_sum, y_sum, n = (hi - lo).T
    herd_ok = n > 0
    safe_n = np.where(herd_ok, n, 1)
    f["herd_resid_28d"] = np.where(herd_ok, r_sum / safe_n, 0.0)
    f["herd_yield_28d"] = np.where(herd_ok, y_sum / safe_n, 0.0)
    f["herd_cows_28d"] = n
    f["herd_level_available"] = herd_ok.astype(float)

    roll = (resid.groupby(f["animal"], sort=False)
            .transform(lambda s: s.rolling(7, min_periods=1).mean()))
    hist = pd.DataFrame({"animal": f["animal"], "last_date": f["date"],
                         "cow_resid": roll}).sort_values("last_date")
    left = pd.DataFrame({"row": np.arange(len(f)), "animal": f["animal"].to_numpy(),
                         "origin": origins}).sort_values("origin")
    m = pd.merge_asof(left, hist, left_on="origin", right_on="last_date", by="animal",
                      allow_exact_matches=False).sort_values("row")
    cow = m["cow_resid"].to_numpy(dtype=float)
    cow_ok = ~np.isnan(cow)
    f["cow_resid_mean7"] = np.where(cow_ok, cow, 0.0)
    f["cow_level_available"] = cow_ok.astype(float)
    f["cow_vs_herd_resid"] = np.where(cow_ok & herd_ok,
                                      np.nan_to_num(cow) - f["herd_resid_28d"], 0.0)
    return f


RECAL_WINDOW_DAYS = 28
RECAL_FALLBACK_DAYS = 365
RECAL_MIN_COW_DAYS = 20
RECAL_PRIOR_COW_DAYS = 200
RECAL_LIMITS = (0.7, 1.4)


def recalibrate(frame: pd.DataFrame, prediction: np.ndarray,
                window: int = RECAL_WINDOW_DAYS, by: np.ndarray | None = None) -> np.ndarray:
    """Rescale predictions by the herd's recent actual/predicted ratio, known at the origin.

    For each row the factor is sum(actual) / sum(prediction) over all recorded cow-days in
    the ``window`` days before its forecast origin (the 365 days before when fewer than
    ``RECAL_MIN_COW_DAYS`` exist), shrunk towards 1 with a prior of
    ``RECAL_PRIOR_COW_DAYS`` cow-days and clipped to ``RECAL_LIMITS``. It uses only
    outcomes dated before the origin, so it is a walk-forward correction of level bias
    (e.g. the 2026 under-prediction) without refitting any weights. With no earlier
    cow-days the factor is 1.

    ``by`` (one label per row) computes the factor separately within each group, using
    only that group's earlier cow-days; see :func:`recalibrate_by_group`.
    """
    pred = np.asarray(prediction, dtype=float)
    if by is not None:
        out = pred.copy()
        labels = pd.Series(by, index=frame.index).astype(str)
        for label in labels.unique():
            idx = (labels == label).to_numpy()
            out[idx] = recalibrate(frame.loc[idx], pred[idx], window)
        return out
    day = frame["date"].dt.normalize()
    origins = pd.DatetimeIndex(pd.to_datetime(frame["origin_date"])).normalize()
    start = min(day.min(), origins.min()) - pd.Timedelta(days=RECAL_FALLBACK_DAYS + 2)
    calendar = pd.date_range(start, day.max() + pd.Timedelta(days=1), freq="D")
    cum = (pd.DataFrame({"d": day, "y": frame["litres"].to_numpy(), "p": pred})
           .groupby("d").agg(y=("y", "sum"), p=("p", "sum"), n=("y", "size"))
           .reindex(calendar, fill_value=0).cumsum())

    def window_sums(days: int) -> np.ndarray:
        hi = cum.reindex(origins - pd.Timedelta(days=1)).to_numpy()
        lo = cum.reindex(origins - pd.Timedelta(days=days + 1)).to_numpy()
        return (hi - lo).T

    y, p, n = window_sums(window)
    y365, p365, n365 = window_sums(RECAL_FALLBACK_DAYS)
    short = n >= RECAL_MIN_COW_DAYS
    y, p, n = (np.where(short, y, y365), np.where(short, p, p365), np.where(short, n, n365))
    ratio = np.where((n > 0) & (p > 0), y / np.where(p > 0, p, 1.0), 1.0)
    weight = n / (n + RECAL_PRIOR_COW_DAYS)
    factor = np.clip(np.exp(weight * np.log(np.clip(ratio, 1e-6, None))), *RECAL_LIMITS)
    return pred * factor


DIM_BANDS = ([0, 60, 150, 305, np.inf], ["1-60", "61-150", "151-305", ">305"])


def parity_dim_group(frame: pd.DataFrame) -> np.ndarray:
    """Label 'parity|DIM band' per row (DIM and parity are known on the day)."""
    band = pd.cut(frame["dim"], *DIM_BANDS).astype(object).fillna("unknown")
    return (frame["parity_group"].astype(str) + "|" + band.astype(str)).to_numpy()


def recalibrate_by_group(frame: pd.DataFrame, prediction: np.ndarray) -> np.ndarray:
    """Herd-level recalibration, then a second factor per parity x DIM-band group.

    Fixes level errors that differ by group (e.g. first-lactation cows under-predicted
    while parity 3+ are over-predicted). Each group factor uses only that group's
    cow-days before the origin and is shrunk towards 1 like the herd factor.
    """
    herd = recalibrate(frame, prediction)
    return recalibrate(frame, herd, by=parity_dim_group(frame))


GAP_BANDS = ([-np.inf, 3, 14, 60, np.inf], ["1-3 days", "4-14 days", "15-60 days", ">60 days"])
BLEND_GRID = np.round(np.linspace(0.0, 1.0, 21), 2)
BLEND_MIN_ROWS = 50


def _gap_band(frame: pd.DataFrame) -> np.ndarray:
    band = pd.cut(frame["days_since_record"], *GAP_BANDS)
    return band.astype(object).where(band.notna(), "no same-lactation record").to_numpy()


def fit_blend_weights(frame: pd.DataFrame, base: np.ndarray, naive: np.ndarray,
                      rows: np.ndarray) -> dict[str, float]:
    """Weight on the model (vs persistence) per days-since-record band, minimising WAPE.

    Bands with fewer than ``BLEND_MIN_ROWS`` rows keep the model alone (weight 1).
    """
    band = _gap_band(frame)
    y = frame["litres"].to_numpy()
    weights = {}
    for name in list(GAP_BANDS[1]) + ["no same-lactation record"]:
        idx = rows & (band == name)
        if idx.sum() < BLEND_MIN_ROWS or name == "no same-lactation record":
            weights[name] = 1.0
            continue
        errors = [np.abs(w * base[idx] + (1 - w) * naive[idx] - y[idx]).sum()
                  for w in BLEND_GRID]
        weights[name] = float(BLEND_GRID[int(np.argmin(errors))])
    return weights


def apply_blend(frame: pd.DataFrame, base: np.ndarray, naive: np.ndarray,
                weights: dict[str, float]) -> np.ndarray:
    w = pd.Series(_gap_band(frame)).map(weights).fillna(1.0).to_numpy()
    return w * np.asarray(base, dtype=float) + (1 - w) * np.asarray(naive, dtype=float)


def add_blend_candidate(models: "AccuracyModels", base_by_grain: dict[str, str],
                        block: str = "validation",
                        use_training_oof: bool = False) -> dict[str, tuple[str, dict]]:
    """Add a ``blend`` prediction per grain: chosen model mixed with persistence.

    Weights are fitted on ``block`` rows. To keep the ``block`` score honest the blend's
    ``block`` predictions are cross-fitted: weights fitted on the first half (by date)
    score the second half and vice versa. Other rows use weights fitted on all ``block``
    rows, which are returned as the spec for :func:`apply_blend_spec`.

    ``use_training_oof``: also fit the weights on training rows, using the models'
    out-of-fold training predictions (``models.oof_predictions``). The training period
    holds far more short-gap rows than the small validation block, so the weight on
    persistence for fresh records can actually be learned.
    """
    spec = {}
    for grain, base_name in base_by_grain.items():
        frame, preds = models.for_grain(grain)
        base = np.asarray(preds[base_name], dtype=float)
        naive = np.asarray(preds["persistence_last_yield"], dtype=float)
        rows = ((frame["period"] == block) & frame["score_eligible"].astype(bool)).to_numpy()
        fit_base, fit_rows = base, rows
        oof = models.oof_predictions.get(grain, {}).get(base_name) if use_training_oof else None
        if oof is not None:
            train = ((frame["period"] == "train")
                     & frame["origin_known_cow"].astype(bool)).to_numpy()
            fit_base = np.where(train, oof, base)
            fit_rows = rows | train
        full = fit_blend_weights(frame, fit_base, naive, fit_rows)
        blended = apply_blend(frame, base, naive, full)
        if rows.any():
            cut = frame.loc[rows, "date"].median()
            first = rows & (frame["date"] <= cut).to_numpy()
            second = rows & ~first
            extra = fit_rows & ~rows  # training rows, if used, join both halves' fits
            for half, score_rows in ((first, second), (second, first)):
                w = fit_blend_weights(frame, fit_base, naive, half | extra)
                blended[score_rows] = apply_blend(frame, base, naive, w)[score_rows]
        preds["blend"] = blended
        spec[grain] = (base_name, full)
    return spec


def apply_blend_spec(models: "AccuracyModels", spec: dict[str, tuple[str, dict]]) -> None:
    """Add ``blend`` predictions using weights fitted earlier (never re-fitted here)."""
    for grain, (base_name, weights) in spec.items():
        frame, preds = models.for_grain(grain)
        preds["blend"] = apply_blend(frame, preds[base_name],
                                     preds["persistence_last_yield"], weights)


def blend_weights_table(spec: dict[str, tuple[str, dict]]) -> pd.DataFrame:
    return pd.DataFrame([{"grain": g, "base_model": b, "days_since_record": band,
                          "weight_on_model": w, "weight_on_persistence": 1 - w}
                         for g, (b, ws) in spec.items() for band, w in ws.items()])


@dataclass
class AccuracyModels:
    frame: pd.DataFrame
    predictions: dict[str, np.ndarray]
    fitted: dict[str, object]
    evaluation_mode: str = "fixed_origin"
    features: tuple[str, ...] = BASE_FEATURES
    # Walk-forward weekly/monthly: frames and predictions with features frozen at the
    # start of each week/month. Missing grains fall back to ``frame``/``predictions``.
    grain_frames: dict[str, pd.DataFrame] = field(default_factory=dict)
    grain_predictions: dict[str, dict[str, np.ndarray]] = field(default_factory=dict)
    grain_fitted: dict[str, dict[str, object]] = field(default_factory=dict)
    # Out-of-fold predictions on training rows (grain -> model -> array), if available.
    oof_predictions: dict[str, dict[str, np.ndarray]] = field(default_factory=dict)
    # Prediction ranges (grain -> model -> (lower, upper) arrays), if a model gives them.
    intervals: dict[str, dict[str, tuple[np.ndarray, np.ndarray]]] = field(default_factory=dict)

    def for_grain(self, grain: str) -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
        return (self.grain_frames.get(grain, self.frame),
                self.grain_predictions.get(grain, self.predictions))


RESIDUAL_MODELS = ("ridge_residual_history", "random_forest_residual_history",
                   "mlp_residual_history", "lgbm_residual_history")


def _fit_residual_models(f: pd.DataFrame, features: tuple[str, ...], wood_pred: np.ndarray,
                         lgbm_kwargs: dict | None, log, verbose: bool,
                         names: set[str] | None = None, n_jobs: int = 1,
                         rf_kwargs: dict | None = None,
                         ) -> tuple[dict[str, object], dict[str, np.ndarray]]:
    """Ridge, random forest, MLP and LightGBM log-corrections to the Wood curve.

    LightGBM and the random forest use ``n_jobs`` CPU threads (default 1).
    """
    from lightgbm import LGBMRegressor
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import Ridge
    from sklearn.neural_network import MLPRegressor
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    train = (f["period"] == "train").to_numpy()
    log_ratio = np.log(f["litres"].to_numpy() / np.maximum(wood_pred, 1e-6))
    # Paper-aligned conventional baselines. All correct the same Wood curve and use
    # exactly the same past-only features as LightGBM, keeping the comparison fair.
    x = _design(f, features)
    params = dict(objective="huber", n_estimators=350, learning_rate=0.03,
                  num_leaves=15, min_child_samples=40, subsample=0.8,
                  colsample_bytree=0.8, reg_lambda=1.0, random_state=17,
                  deterministic=True, force_row_wise=True, n_jobs=n_jobs,
                  verbose=1 if verbose else -1)
    params.update(lgbm_kwargs or {})
    candidates = {
        "ridge_residual_history": make_pipeline(
            SimpleImputer(strategy="median", add_indicator=True),
            StandardScaler(),
            Ridge(alpha=10.0),
        ),
        "random_forest_residual_history": make_pipeline(
            SimpleImputer(strategy="median", add_indicator=True),
            RandomForestRegressor(**{
                **dict(n_estimators=250, min_samples_leaf=20, max_features=0.8,
                       random_state=17),
                **(rf_kwargs or {}), "n_jobs": n_jobs,
            }),
        ),
        # Compact two-hidden-layer neural candidate. Scikit-learn's built-in early
        # stopping uses a random validation subset, so it is disabled here.
        "mlp_residual_history": make_pipeline(
            SimpleImputer(strategy="median", add_indicator=True),
            StandardScaler(),
            MLPRegressor(
                hidden_layer_sizes=(32, 16), activation="relu", solver="adam",
                alpha=1e-3, batch_size=128, learning_rate_init=1e-3,
                early_stopping=False,
                max_iter=250, random_state=17, verbose=False,
            ),
        ),
        "lgbm_residual_history": LGBMRegressor(**params),
    }
    fitted, predictions = {}, {}
    n_train = int(train.sum())
    for name, model in candidates.items():
        if names is not None and name not in names:
            continue
        where = (f"{n_jobs} CPU thread(s)" if name in {"lgbm_residual_history",
                                                        "random_forest_residual_history"}
                 else "1 CPU thread")
        log(f"fitting {name}: {n_train:,} train rows x {x.shape[1]} columns ({where})")
        t0 = time.perf_counter()
        model.fit(x.loc[train], log_ratio[train])
        fit_s = time.perf_counter() - t0
        t0 = time.perf_counter()
        predictions[name] = wood_pred * np.exp(np.clip(model.predict(x), -0.7, 0.7))
        extra = ""
        if name == "mlp_residual_history":
            extra = f", {model[-1].n_iter_} epochs"
        elif name == "lgbm_residual_history":
            extra = f", {model.booster_.num_trees()} trees"
        log(f"  {name} fitted in {fit_s:,.1f}s, predicted {len(x):,} rows in "
            f"{time.perf_counter() - t0:,.1f}s{extra}")
        fitted[name] = model
    return fitted, predictions


def _grain_job(grain: str, fx: pd.DataFrame | None, prep_kwargs: dict, raw: pd.DataFrame,
               reference: pd.DataFrame, wood_pred: np.ndarray, curves: dict,
               features: tuple[str, ...], names: set[str] | None, lgbm_kwargs: dict | None,
               n_jobs: int, verbose: bool, rf_kwargs: dict | None = None) -> tuple:
    """Prepare one grain's frame (if needed) and fit its residual models.

    Runs in a worker process; log lines are returned so the notebook can print them.
    """
    lines: list[str] = []
    started = time.perf_counter()

    def log(message: str) -> None:
        if verbose:
            lines.append(f"[cow-accuracy] {message}")

    if fx is None:
        t0 = time.perf_counter()
        fx = prepare_accuracy_frame(raw, origin_grain=grain, **prep_kwargs)
        if not (fx[["animal", "date"]].to_numpy() == reference.to_numpy()).all():
            raise AssertionError("grain frame rows differ from the daily frame")
        log(f"{grain}: frame prepared in {time.perf_counter() - t0:,.1f}s")
    counts = fx["period"].value_counts().to_dict()
    log(f"{grain} residual models" + (" (one day ahead)" if grain == "daily"
                                      else " (features frozen at the start of each period)")
        + f": rows by block {counts}, scoreable holdout rows "
        f"{int(fx['score_eligible'].sum()):,}, process {os.getpid()}")
    fx = _add_level_features(fx, wood_pred)
    # Naive benchmark: the cow's latest record known at the forecast origin.
    preds = {"persistence_last_yield": fx["yield_lag1"].fillna(
        pd.Series(wood_pred, index=fx.index)).to_numpy(dtype=float)}
    preds.update(curves)
    models, residual = _fit_residual_models(fx, features, wood_pred, lgbm_kwargs, log,
                                            verbose, names=names, n_jobs=n_jobs,
                                            rf_kwargs=rf_kwargs)
    preds.update(residual)
    # Walk-forward level recalibration of every model (not of persistence itself).
    for name in [n for n in preds if n != "persistence_last_yield"]:
        preds[f"{name}_recal"] = recalibrate(fx, preds[name])
    log(f"{grain}: done in {time.perf_counter() - started:,.1f}s "
        f"({len(preds)} candidates incl. recalibrated)")
    return grain, fx, models, preds, lines


def fit_accuracy_models(raw: pd.DataFrame, include_ebm: bool = True,
                        lgbm_kwargs: dict | None = None,
                        ebm_kwargs: dict | None = None,
                        train_end: date = FINAL_TRAIN_END,
                        validation_end: date = FINAL_TRAIN_END,
                        evaluation_mode: str = "fixed_origin",
                        events: dict | None = None,
                        min_source_records: int = DEFAULT_MIN_RECORDS,
                        residual_models: dict[str, set[str]] | None = None,
                        n_jobs: int | None = 1, parallel_grains: bool = False,
                        rf_kwargs: dict | None = None,
                        verbose: bool = False) -> AccuracyModels:
    """Fit only through ``train_end`` and predict the complete chronological frame.

    ``residual_models`` (grain -> model names) limits which residual models are fitted
    per grain; ``None`` fits all four. Persistence and the curves are always returned.

    In ``walk_forward`` mode the residual models are fitted once per grain: daily models
    forecast one day ahead; weekly and monthly models are trained and scored with every
    feature frozen at the start of the week or month (direct multi-step forecasts).

    Compute: by default everything runs in this process, one grain after another, with
    ``n_jobs`` CPU threads for LightGBM and the random forest. ``parallel_grains`` runs
    the grains in separate processes (optional; off by default).
    """
    def log(message: str) -> None:
        if verbose:
            print(f"[cow-accuracy] {message}")

    started = time.perf_counter()
    prep_kwargs = dict(train_end=train_end, validation_end=validation_end,
                       evaluation_mode=evaluation_mode, events=events,
                       min_source_records=min_source_records)
    f = prepare_accuracy_frame(raw, origin_grain="daily", **prep_kwargs)
    log(f"daily frame prepared in {time.perf_counter() - started:,.1f}s: "
        f"{f['animal'].nunique():,} cows, {f['date'].nunique():,} days")
    features = (BASE_FEATURES + tuple(f.attrs.get("event_features", ()))
                + LEVEL_FEATURES)
    fitted: dict[str, object] = {}
    predictions: dict[str, np.ndarray] = {}
    counts = f.groupby("period").size().to_dict()
    log(f"prepared {len(f):,} cow-days; aggregate split counts={counts}")
    log(f"residual models use {len(features)} features "
        f"({len(features) - len(BASE_FEATURES) - len(LEVEL_FEATURES)} "
        f"health/treatment/sensor/weather, {len(LEVEL_FEATURES)} recent level)")

    # Glass-box lactation curves use no yield history, so one fit serves every grain.
    split = CowSplit(start=TRAIN_START, train_end=train_end, validate_end=validation_end,
                     gap_end=validation_end, recal_end=validation_end)
    fitting = prepare_cowdays(f, split)
    n_curve = int((fitting["usable"] & (fitting["period"] == "train")).sum())
    log(f"fitting Wood mixed-effects baseline on {n_curve:,} usable train cow-days")
    t0 = time.perf_counter()
    wood = fit_wood_mixed(fitting, calendar_level=True)
    wood_pred = wood.predict(fitting)
    log(f"  wood_mixed fitted in {time.perf_counter() - t0:,.1f}s")
    fitted["wood_mixed"] = wood
    curves = {"wood_mixed": wood_pred}
    if include_ebm:
        log(f"fitting explainable boosting curve on {n_curve:,} usable train cow-days")
        t0 = time.perf_counter()
        ebm = fit_ebm(fitting, calendar_level=True, **(ebm_kwargs or {}))
        fitted["ebm_curve"] = ebm
        curves["ebm_curve"] = ebm.predict(fitting)
        log(f"  ebm_curve fitted in {time.perf_counter() - t0:,.1f}s")

    grains = ["daily"] + (["weekly", "monthly"] if evaluation_mode == "walk_forward" else [])
    workers = len(grains) if parallel_grains else 1
    threads = max(1, cpu_cores(n_jobs) // workers)
    log(f"fitting {len(grains)} grain(s) in {workers} process(es), {threads} CPU thread(s) "
        f"each")
    reference = f[["animal", "date"]]
    jobs = [(g, f if g == "daily" else None) for g in grains]
    common = dict(prep_kwargs=prep_kwargs, raw=raw, reference=reference,
                  wood_pred=wood_pred, curves=curves, features=features,
                  lgbm_kwargs=lgbm_kwargs, rf_kwargs=rf_kwargs, n_jobs=threads,
                  verbose=verbose)

    def names_for(grain: str) -> set[str] | None:
        return None if residual_models is None else set(residual_models.get(grain, ()))

    if workers > 1:
        from joblib import Parallel, delayed
        results = Parallel(n_jobs=workers, backend="loky")(
            delayed(_grain_job)(g, fx, names=names_for(g), **common) for g, fx in jobs)
    else:
        results = [_grain_job(g, fx, names=names_for(g), **common) for g, fx in jobs]

    out = None
    for grain, fx, models, preds, lines in results:
        for line in lines:
            print(line)
        if grain == "daily":
            fitted.update(models)
            predictions = preds
            out = AccuracyModels(fx, preds, fitted, evaluation_mode=evaluation_mode,
                                 features=features)
        else:
            out.grain_frames[grain] = fx
            out.grain_fitted[grain] = models
            out.grain_predictions[grain] = preds
    log(f"finished {len(predictions)} candidate models in "
        f"{time.perf_counter() - started:,.1f}s total")
    return out


_SCORE_COLUMNS = ("animal", "date", "period", "litres", "score_eligible", "evaluation_mode",
                  "yield_lag1", "origin_date")


def _backtest_fold(year: int, raw: pd.DataFrame, dates: pd.Series, by_grain: dict,
                   residual: dict, need_ebm: bool, test_start: date, events: dict | None,
                   min_source_records: int, lgbm_kwargs: dict | None,
                   ebm_kwargs: dict | None, verbose: bool, n_jobs: int,
                   rf_kwargs: dict | None,
                   parallel_grains: bool) -> tuple[dict, dict, dict]:
    """One yearly fold: fit on data before the fold, keep forecasts issued in ``year``."""
    train_end = max(date(year - 1, 12, 31), test_start - timedelta(days=1))
    year_rows = (dates.dt.year == year) & (dates > pd.Timestamp(train_end))
    if not year_rows.any():
        return ({"test_year": year, "train_end": train_end, "train_cow_days": 0,
                 "test_cow_days": 0, "status": "insufficient data", "seconds": 0.0,
                 "log": ""}, {}, {})
    started = time.perf_counter()
    # A Monday-start week can begin in Y and end in Y+1: those days belong to the
    # fold of their origin, so keep up to 6 days of spill-over.
    sub = raw[dates <= pd.Timestamp(date(year, 12, 31)) + pd.Timedelta(days=6)]
    buffer = io.StringIO()  # worker-process prints would not reach the notebook
    with contextlib.redirect_stdout(buffer):
        print(f"[cow-backtest] fold {year}: train through {train_end}, "
              f"{int(year_rows.sum()):,} test cow-days, process {os.getpid()}")
        models = fit_accuracy_models(
            sub, include_ebm=need_ebm, lgbm_kwargs=lgbm_kwargs, ebm_kwargs=ebm_kwargs,
            train_end=train_end, validation_end=train_end, evaluation_mode="walk_forward",
            events=events, min_source_records=min_source_records,
            residual_models=residual, n_jobs=n_jobs, rf_kwargs=rf_kwargs,
            parallel_grains=parallel_grains, verbose=verbose,
        )
    parts, preds = {}, {}
    for grain, names in by_grain.items():
        frame, grain_preds = models.for_grain(grain)
        # Assign each row to the fold of its forecast origin, so model weights never
        # include data dated after the origin. Training rows are kept for chart context.
        keep = (((pd.to_datetime(frame["origin_date"]).dt.year == year).to_numpy()
                 & (frame["period"] == "test").to_numpy())
                | (frame["period"] == "train").to_numpy())
        parts[grain] = frame.loc[keep, list(_SCORE_COLUMNS)].reset_index(drop=True)
        preds[grain] = {name: np.asarray(grain_preds[name])[keep] for name in names}
    seconds = time.perf_counter() - started
    fold = {"test_year": year, "train_end": train_end,
            "train_cow_days": int((models.frame["period"] == "train").sum()),
            "test_cow_days": int(year_rows.sum()), "status": "fitted",
            "seconds": round(seconds, 1),
            "log": buffer.getvalue() + (f"[cow-backtest] fold {year} done in {seconds:,.1f}s\n"
                                        if verbose else "")}
    return fold, parts, preds


def expanding_backtest(raw: pd.DataFrame, selected: dict[str, set[str]],
                       test_years: tuple[int, ...] | None = None,
                       test_start: date = TEST_START,
                       events: dict | None = None,
                       min_source_records: int = DEFAULT_MIN_RECORDS,
                       include_ebm: bool = False,
                       lgbm_kwargs: dict | None = None,
                       ebm_kwargs: dict | None = None,
                       n_jobs: int | None = 1, parallel_folds: int = 1,
                       blend_spec: dict | None = None,
                       rf_kwargs: dict | None = None,
                       verbose: bool = False) -> tuple[AccuracyModels, pd.DataFrame]:
    """Refit the validation-selected models every year on all data before that year.

    For test year *Y* the models are fitted on cow-days up to 31 Dec *Y-1* (or the day
    before ``test_start`` in its first year, whichever is later) and scored
    walk-forward on forecasts issued in *Y* (daily one day ahead; weekly/monthly from the
    period start).
    This lets sources that only start later (treatments and sensors from 2020) enter the
    model once they exist, and lets the yield level adapt year by year. ``selected`` is
    the validation winner map (model -> grains); the test never changes it.
    Returns the combined models for ``score_models`` and an aggregate fold table.

    ``parallel_folds`` runs that many yearly folds at once in separate processes, sharing
    the ``n_jobs`` CPU cores; within a fold the grains then run one after another.
    """
    def log(message: str) -> None:
        if verbose:
            print(f"[cow-backtest] {message}")

    by_grain: dict[str, set[str]] = {"daily": set(), "weekly": set(), "monthly": set()}
    for model, grains in selected.items():
        for grain in grains:
            by_grain[grain].add(model)
    for grain, (base_name, _) in (blend_spec or {}).items():
        if "blend" in by_grain[grain]:
            by_grain[grain] |= {base_name, "persistence_last_yield"}
    residual = {g: {m.removesuffix("_recal") for m in names
                    if m.removesuffix("_recal") in RESIDUAL_MODELS}
                for g, names in by_grain.items()}
    need_ebm = include_ebm or any(m.startswith("ebm_curve") for names in by_grain.values()
                                  for m in names)
    fitted_names = {g: {m for m in names if m != "blend"} for g, names in by_grain.items()}

    if test_years is None:
        test_years = tuple(range(test_start.year, TEST_END.year + 1))
    dates = pd.to_datetime(raw["date"])
    parts: dict[str, list[pd.DataFrame]] = {g: [] for g in by_grain}
    preds: dict[str, dict[str, list[np.ndarray]]] = {
        g: {m: [] for m in names if m != "blend"} for g, names in by_grain.items()}
    folds = []
    workers = max(1, min(int(parallel_folds), len(test_years)))
    kwargs = dict(raw=raw, dates=dates, by_grain=fitted_names, residual=residual,
                  rf_kwargs=rf_kwargs,
                  need_ebm=need_ebm, test_start=test_start, events=events,
                  min_source_records=min_source_records, lgbm_kwargs=lgbm_kwargs,
                  ebm_kwargs=ebm_kwargs, verbose=verbose,
                  n_jobs=max(1, cpu_cores(n_jobs) // workers),
                  parallel_grains=False)
    log(f"{len(test_years)} folds, {workers} at a time, "
        f"{kwargs['n_jobs']} CPU thread(s) per fold")
    started = time.perf_counter()
    if workers > 1:
        from joblib import Parallel, delayed
        results = Parallel(n_jobs=workers, backend="loky")(
            delayed(_backtest_fold)(year, **kwargs) for year in test_years)
    else:
        results = [_backtest_fold(year, **kwargs) for year in test_years]

    for fold, fold_parts, fold_preds in sorted(results, key=lambda r: r[0]["test_year"]):
        if verbose and fold["log"]:
            print(fold["log"], end="")
        folds.append({k: v for k, v in fold.items() if k != "log"})
        for grain in by_grain:
            if grain in fold_parts:
                if parts[grain]:  # training history only once, for chart context
                    keep = (fold_parts[grain]["period"] != "train").to_numpy()
                else:
                    keep = np.ones(len(fold_parts[grain]), dtype=bool)
                parts[grain].append(fold_parts[grain][keep])
                for name in fitted_names[grain]:
                    preds[grain][name].append(fold_preds[grain][name][keep])

    fitted_seconds = sum(f["seconds"] for f in folds)
    log(f"all folds done in {time.perf_counter() - started:,.1f}s wall time "
        f"({fitted_seconds:,.1f}s summed over folds)")
    frames = {g: pd.concat(p, ignore_index=True) for g, p in parts.items() if p}
    if not frames:
        raise ValueError("no test year has cow-days")
    out = AccuracyModels(
        frame=frames["daily"],
        predictions={m: np.concatenate(v) for m, v in preds["daily"].items()},
        fitted={}, evaluation_mode="walk_forward",
        grain_frames={g: frames[g] for g in ("weekly", "monthly")},
        grain_predictions={g: {m: np.concatenate(v) for m, v in preds[g].items()}
                           for g in ("weekly", "monthly")},
    )
    if blend_spec:
        apply_blend_spec(out, {g: v for g, v in blend_spec.items() if "blend" in by_grain[g]})
    return out, pd.DataFrame(folds)


def safe_column_profile(frame: pd.DataFrame) -> pd.DataFrame:
    """Column-level EDA only: no values, examples or identifier columns."""
    blocked = {"animal", "cow_id", "animal_key", "record_key", "group_key"}
    rows = []
    for column in frame.columns:
        if column in blocked:
            continue
        series = frame[column]
        rows.append({
            "column": column,
            "dtype": str(series.dtype),
            "non_null": int(series.notna().sum()),
            "missing_pct": 100.0 * float(series.isna().mean()),
            "unique_count": int(series.nunique(dropna=True)),
        })
    return pd.DataFrame(rows).sort_values("column").reset_index(drop=True)


_FAMILY_NOTES = {
    "health": ("core.health_episode", "episodes started before t: 30/365-day counts, days "
               "since, active milk withhold, one-hot counts of top training labels"),
    "treatment": ("core.treatment_history", "treatments started before t: 30/365-day counts, "
                  "days since, active course, diverted-milk count, top treatment names"),
    "thi_prev_day": ("core.weather_day", "THI of the previous calendar day"),
}


def feature_catalogue(event_features: tuple[str, ...] | list[str] = ()) -> pd.DataFrame:
    """Document engineered predictors and whether they are usable at forecast issue time."""
    descriptions = {
        "dim": ("lactation", "projected from last training DIM", "frozen at origin"),
        "age_days": ("animal", "projected from age at last training record", "frozen at origin"),
        "doy_sin": ("calendar", "cyclical day-of-year sine", "known in advance"),
        "doy_cos": ("calendar", "cyclical day-of-year cosine", "known in advance"),
        "yield_lag1": ("past yield", "last same-lactation yield before the origin", "frozen at origin"),
        "yield_mean7": ("past yield", "last 7-record mean at origin", "frozen at origin"),
        "yield_mean28": ("past yield", "last 28-record mean at origin", "frozen at origin"),
        "yield_sd28": ("past yield", "last 28-record SD at origin", "frozen at origin"),
        "days_since_record": ("past yield", "days since the last same-lactation record (cap 400)", "known in advance"),
        "days_since_any_record": ("past yield", "days since any earlier record (cap 400)", "known in advance"),
        "prev_lactation_mean": ("past yield", "mean yield of the most recent earlier lactation", "frozen at origin"),
        "lactation_history_n": ("past yield", "same-lactation records before the origin", "frozen at origin"),
        "cow_records_28d": ("past yield", "records of the cow in the 28 days before the origin", "frozen at origin"),
    }
    rows = []
    for feature in BASE_FEATURES:
        source, engineering, availability = descriptions[feature]
        rows.append({"feature": feature, "source": source, "engineering": engineering,
                     "forecast_availability": availability,
                     "used_by": "all residual models"})
    rows.append({"feature": "parity_*", "source": "lactation",
                 "engineering": "one-hot parity frozen at origin",
                 "forecast_availability": "frozen at origin", "used_by": "all models"})
    for feature in event_features:
        family = feature_family(feature)
        if feature.endswith("_available") or feature.endswith("_unavailable"):
            engineering = ("1 when the source is recorded for this year/cow"
                           if feature.endswith("_available")
                           else "1 when the source table has no records that year")
        else:
            engineering = _FAMILY_NOTES.get(
                family, ("core.daily_milk", "value from the cow's previous record"))[1]
        rows.append({"feature": feature,
                     "source": _FAMILY_NOTES.get(family, ("core.daily_milk (lagged)",))[0],
                     "engineering": engineering,
                     "forecast_availability": "strictly before t; 0 + flag when unavailable",
                     "used_by": "all residual models"})
    for feature in EXCLUDED_SAME_DAY_FEATURES:
        rows.append({"feature": feature, "source": "same-day source",
                     "engineering": "same-day value not used (previous-record lag is)",
                     "forecast_availability": "excluded: unavailable at forecast origin",
                     "used_by": "none"})
    return pd.DataFrame(rows)


def lgbm_shap_summary(models: AccuracyModels, model_name: str,
                      period: str = "validation", max_rows: int = 2000) -> pd.DataFrame:
    """Aggregate LightGBM TreeSHAP contributions; never return per-row explanations."""
    if model_name != "lgbm_residual_history":
        raise ValueError("TreeSHAP summary is available only for the origin-safe LightGBM model")
    x = _design(models.frame, models.features)
    eligible = ((models.frame["period"].to_numpy() == "train")
                | models.frame["score_eligible"].to_numpy(dtype=bool))
    positions = np.flatnonzero((models.frame["period"].to_numpy() == period) & eligible)
    if not len(positions):
        raise ValueError(f"no rows in period {period!r}")
    if len(positions) > max_rows:
        positions = positions[np.linspace(0, len(positions) - 1, max_rows, dtype=int)]
    contribution = np.asarray(models.fitted[model_name].predict(
        x.iloc[positions], pred_contrib=True,
    ))
    # LightGBM's last contribution is the expected-value baseline, not a feature.
    contribution = contribution[:, :-1]
    out = pd.DataFrame({
        "feature": x.columns,
        "mean_abs_shap_log_correction": np.mean(np.abs(contribution), axis=0),
        "mean_signed_shap_log_correction": np.mean(contribution, axis=0),
    })
    out["importance_pct"] = 100 * out["mean_abs_shap_log_correction"] / max(
        out["mean_abs_shap_log_correction"].sum(), 1e-12)
    return out.sort_values("mean_abs_shap_log_correction", ascending=False).reset_index(drop=True)


def split_accuracy_frames(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Return disjoint internal train/validation/test dataframes.

    These frames may contain the per-run integer needed by the estimators and therefore
    must not be displayed or written. Use :func:`safe_split_summary` for notebook output.
    """
    parts = {name: frame[frame["period"] == name].copy()
             for name in ("train", "validation", "test")}
    indexes = [set(part.index) for part in parts.values()]
    assert not (indexes[0] & indexes[1] or indexes[0] & indexes[2] or indexes[1] & indexes[2])
    return parts


def safe_split_summary(parts: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Aggregate-only description of explicit split dataframes."""
    rows = []
    for name, part in parts.items():
        eligible = part.get("score_eligible", pd.Series(False, index=part.index)).astype(bool)
        rows.append({
            "dataframe": f"{name}_df",
            "start": part["date"].min() if len(part) else pd.NaT,
            "end": part["date"].max() if len(part) else pd.NaT,
            "cow_days": len(part),
            "cows": part["animal"].nunique(),
            "scoreable_cow_days": int(eligible.sum()),
        })
    return pd.DataFrame(rows)


def _period_start(dates: pd.Series, grain: str) -> pd.Series:
    dates = pd.to_datetime(dates)
    if grain == "daily":
        return dates.dt.normalize()
    if grain == "weekly":
        return dates.dt.normalize() - pd.to_timedelta(dates.dt.dayofweek, unit="D")
    if grain == "monthly":
        return dates.dt.to_period("M").dt.to_timestamp()
    raise ValueError("grain must be daily, weekly or monthly")


def _cow_period_prediction(frame: pd.DataFrame, prediction: np.ndarray, model: str,
                           grain: str, min_cows: int,
                           min_coverage: float,
                           naive: np.ndarray | None = None,
                           ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return private cow-period rows and identifier-free mean-yield chart rows."""
    if len(frame) != len(prediction):
        raise ValueError("prediction length differs from frame")
    mode = (str(frame["evaluation_mode"].iloc[0])
            if "evaluation_mode" in frame and len(frame) else "fixed_origin")
    s = frame[["animal", "date", "period", "litres", "score_eligible"]].assign(
        prediction=np.asarray(prediction, dtype=float),
        naive=np.asarray(prediction if naive is None else naive, dtype=float),
    )
    # Training history is shown for context; holdout rows must pass the fixed-origin gate.
    s = s[(s["period"] == "train") | s["score_eligible"]].copy()
    s["period_start"] = _period_start(s["date"], grain)
    private = (s.groupby(["animal", "period_start", "period"], as_index=False)
               .agg(actual=("litres", "sum"), prediction=("prediction", "sum"),
                    naive=("naive", "sum"), observed_days=("date", "nunique")))
    private["error"] = private["prediction"] - private["actual"]
    private["abs_error"] = private["error"].abs()
    private["squared_error"] = private["error"] ** 2
    private["ape"] = private["abs_error"] / private["actual"]
    private["sape"] = 2 * private["abs_error"] / (
        private["actual"].abs() + private["prediction"].abs()).replace(0, np.nan)
    private["naive_abs_error"] = (private["naive"] - private["actual"]).abs()
    private["actual_sq"] = private["actual"] ** 2
    private["prediction_sq"] = private["prediction"] ** 2
    private["cross"] = private["actual"] * private["prediction"]
    for pct in (5, 10, 20):
        private[f"within_{pct}pct"] = private["abs_error"] <= pct / 100 * private["actual"]

    calendar = (s.groupby(["period_start", "period"], as_index=False)
                .agg(valid_days=("date", "nunique")))
    public = (private.groupby(["period_start", "period"], as_index=False)
              .agg(recorded_cows=("animal", "nunique"), cow_periods=("animal", "size"),
                   cow_days=("observed_days", "sum"),
                   actual_sum=("actual", "sum"), error_sum=("error", "sum"),
                   abs_error_sum=("abs_error", "sum"),
                   squared_error_sum=("squared_error", "sum"),
                   ape_sum=("ape", "sum"), sape_sum=("sape", "sum"),
                   naive_abs_error_sum=("naive_abs_error", "sum"),
                   prediction_sum=("prediction", "sum"),
                   actual_sq_sum=("actual_sq", "sum"),
                   prediction_sq_sum=("prediction_sq", "sum"),
                   cross_sum=("cross", "sum"),
                   within_5pct_count=("within_5pct", "sum"),
                   within_10pct_count=("within_10pct", "sum"),
                   within_20pct_count=("within_20pct", "sum")))
    # Public charts show mean yield per recorded cow-day at every grain. A monthly
    # point is therefore comparable with a daily point and cannot be mistaken for a
    # herd total, shipment total or placeholder-inclusive period sum.
    public["actual"] = public["actual_sum"] / public["cow_days"]
    public["prediction"] = (
        public["actual_sum"] + public["error_sum"]
    ) / public["cow_days"]
    public = public.merge(calendar, on=["period_start", "period"], how="left")
    index = pd.DatetimeIndex(public["period_start"])
    public["expected_days"] = _expected_days(index, grain)
    public["coverage"] = public["valid_days"] / public["expected_days"]
    public["model"] = model
    public["evaluation_mode"] = mode
    public["scoreable"] = ((public["recorded_cows"] >= min_cows)
                           & (public["coverage"] >= min_coverage))
    accepted = public.loc[public["scoreable"], "period_start"]
    private = private[private["period_start"].isin(accepted)].copy()
    public = public[public["scoreable"]].reset_index(drop=True)
    assert not ({"animal", "cow_id", "animal_key"} & set(public.columns))
    return private, public


def daily_prediction(frame: pd.DataFrame, prediction: np.ndarray, model: str,
                     min_cows: int = MIN_COWS_PER_DAY) -> pd.DataFrame:
    """Identifier-free daily mean cow yield for plotting, never a herd total."""
    _, public = _cow_period_prediction(
        frame, prediction, model, "daily", min_cows, min_coverage=0.0,
    )
    return public.rename(columns={"period_start": "date"})


def _expected_days(index: pd.DatetimeIndex, grain: str) -> np.ndarray:
    if grain == "daily":
        return np.ones(len(index), dtype=int)
    if grain == "weekly":
        return np.full(len(index), 7, dtype=int)
    return index.days_in_month.to_numpy()


def aggregate_grain(daily: pd.DataFrame, grain: str,
                    min_coverage: float = MIN_PERIOD_COVERAGE) -> pd.DataFrame:
    """Aggregate public daily mean-cow diagnostics; not used for metric calculation."""
    if grain not in {"daily", "weekly", "monthly"}:
        raise ValueError("grain must be daily, weekly or monthly")
    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"])
    d = d.set_index("date").sort_index()
    calendar = d.reindex(pd.date_range(d.index.min(), d.index.max(), freq="D"))
    valid = calendar["scoreable"].astype("boolean").fillna(False).astype(bool)
    calendar["actual_ok"] = calendar["actual"].where(valid)
    calendar["prediction_ok"] = calendar["prediction"].where(valid)
    calendar["valid_day"] = valid.astype(int)
    calendar["period"] = calendar["period"].ffill().bfill()
    calendar["model"] = daily["model"].iloc[0]

    if grain == "daily":
        out = calendar.loc[valid, ["period", "model", "actual_ok", "prediction_ok",
                                   "valid_day"]].rename(
            columns={"actual_ok": "actual", "prediction_ok": "prediction"})
        out["expected_days"], out["coverage"] = 1, 1.0
        out.index.name = "period_start"
        return out.reset_index()

    # Monday-start weeks match model_input2.period_panel and the frontend contract.
    rule = "W-MON" if grain == "weekly" else "MS"
    r = calendar.resample(rule, label="left", closed="left")
    out = pd.DataFrame({
        "period": r["period"].first(),
        "model": r["model"].first(),
        "actual": r["actual_ok"].mean(),
        "prediction": r["prediction_ok"].mean(),
        "valid_day": r["valid_day"].sum(),
    })
    out["expected_days"] = _expected_days(out.index, grain)
    out["coverage"] = out["valid_day"] / out["expected_days"]
    out = out[out["coverage"] >= min_coverage]
    out.index.name = "period_start"
    return out.reset_index()


def score_models(models: AccuracyModels, min_cows: int = MIN_COWS_PER_DAY,
                 min_coverage: float = MIN_PERIOD_COVERAGE,
                 blocks: tuple[str, ...] = ("validation", "test"),
                 selected: dict[str, set[str]] | None = None,
                 ) -> tuple[pd.DataFrame, dict[str, dict[str, pd.DataFrame]]]:
    """Score cow-period errors before public aggregation at all three grains.

    Every metric is computed on individual cow-period errors (see ``_metrics_from_sums``).
    ``skill_vs_persistence_pct`` compares MAE with the cow's latest earlier record.
    """
    rows, frames = [], {}
    names = list(dict.fromkeys(
        list(models.predictions)
        + [m for preds in models.grain_predictions.values() for m in preds]))
    for model in names:
        if selected is not None and model not in selected:
            continue
        frames[model] = {}
        for grain in ("daily", "weekly", "monthly"):
            if selected is not None and grain not in selected[model]:
                continue
            frame, grain_predictions = models.for_grain(grain)
            if model not in grain_predictions:
                continue
            pred = grain_predictions[model]
            naive = grain_predictions.get("persistence_last_yield")
            if naive is None and "yield_lag1" in frame:
                naive = frame["yield_lag1"].fillna(pd.Series(pred, index=frame.index)).to_numpy(
                    dtype=float)
            private, public = _cow_period_prediction(
                frame, pred, model, grain, min_cows, min_coverage, naive=naive,
            )
            frames[model][grain] = public
            for block in blocks:
                q = public[public["period"] == block]
                p = private[private["period"] == block]
                rows.append({
                    "block": block, "model": model, "grain": grain,
                    **_metrics_from_sums(q, grain),
                    "cows": p["animal"].nunique(),
                    "median_ape_pct": 100 * float(p["ape"].median()) if len(p) else np.nan,
                })
    return pd.DataFrame(rows)[METRIC_COLUMNS], frames


METRIC_COLUMNS = [
    "block", "model", "grain", "status", "evaluation_unit", "periods", "calendar_periods",
    "cows", "cow_days", "accuracy_pct", "within_5pct", "within_10pct", "within_20pct",
    "mae_per_cow_day", "mae", "rmse", "bias", "wape_pct", "mape_pct", "median_ape_pct", "smape_pct",
    "bias_pct", "r2", "pearson_r", "mase", "skill_vs_persistence_pct",
    "mean_actual", "mean_prediction", "mean_actual_per_cow_day",
]


def _metrics_from_sums(q: pd.DataFrame, grain: str) -> dict:
    """Pool cow-period sufficient statistics into accuracy metrics (no error cancellation).

    - ``accuracy_pct`` = 100 - WAPE: share of recorded litres predicted correctly.
    - ``within_k pct``: % of cow-periods whose absolute error is at most k% of actual.
    - ``mape_pct``/``smape_pct``: mean (symmetric) absolute percentage error per cow-period.
    - ``r2``/``pearson_r``: explained variance and correlation across cow-periods.
    - ``mase``: MAE / MAE of persistence; ``skill_vs_persistence_pct`` = 100 * (1 - mase).
    - ``mae``/``mean_actual`` are per evaluation unit (a cow-week or cow-month sums its
      recorded days); ``mae_per_cow_day`` divides by recorded cow-days, so it is
      comparable across grains.
    - ``status`` is ``insufficient data`` when no cow-period could be scored.
    """
    n = float(q["cow_periods"].sum()) if len(q) else 0.0
    days = float(q["cow_days"].sum()) if len(q) and "cow_days" in q else 0.0
    unit = {"daily": "cow_day", "weekly": "cow_week", "monthly": "cow_month"}[grain]
    base = {"status": "scored" if n else "insufficient data", "evaluation_unit": unit,
            "periods": int(n), "calendar_periods": len(q), "cow_days": int(days)}
    if n == 0:
        return base | {c: np.nan for c in METRIC_COLUMNS if c not in base
                       and c not in {"block", "model", "grain", "cows"}}
    sy, sp = q["actual_sum"].sum(), q["prediction_sum"].sum()
    sae, sse = q["abs_error_sum"].sum(), q["squared_error_sum"].sum()
    syy, spp, syp = q["actual_sq_sum"].sum(), q["prediction_sq_sum"].sum(), q["cross_sum"].sum()
    naive = q["naive_abs_error_sum"].sum()
    sst = syy - sy ** 2 / n
    corr_den = np.sqrt(max(n * syy - sy ** 2, 0) * max(n * spp - sp ** 2, 0))
    wape = 100 * sae / sy if sy > 0 else np.nan
    mase = sae / naive if naive > 0 else np.nan
    return base | {
        "accuracy_pct": 100 - wape,
        "within_5pct": 100 * q["within_5pct_count"].sum() / n,
        "within_10pct": 100 * q["within_10pct_count"].sum() / n,
        "within_20pct": 100 * q["within_20pct_count"].sum() / n,
        "mae": sae / n, "rmse": float(np.sqrt(sse / n)), "bias": q["error_sum"].sum() / n,
        "wape_pct": wape,
        "mape_pct": 100 * q["ape_sum"].sum() / n,
        "median_ape_pct": np.nan,
        "smape_pct": 100 * q["sape_sum"].sum() / n,
        "bias_pct": 100 * q["error_sum"].sum() / sy if sy > 0 else np.nan,
        "r2": 1 - sse / sst if sst > 0 else np.nan,
        "pearson_r": (n * syp - sy * sp) / corr_den if corr_den > 0 else np.nan,
        "mase": mase,
        "skill_vs_persistence_pct": 100 * (1 - mase) if mase == mase else np.nan,
        "mean_actual": sy / n, "mean_prediction": sp / n,
        "mae_per_cow_day": sae / days if days else np.nan,
        "mean_actual_per_cow_day": sy / days if days else np.nan,
    }


def pool_metrics(tables: list[pd.DataFrame], label: str = "pooled") -> pd.DataFrame:
    """Pool cow-period WAPE across several scored blocks (validation, windows, ...).

    Rebuilds each block's absolute-error and actual sums from its metrics
    (``wape_pct``, ``mean_actual``, ``periods``) and pools them, so a large block weighs
    more than a small one. Only models scored in every block are kept.
    """
    parts = []
    for i, t in enumerate(tables):
        q = t[t["status"] == "scored"].copy()
        q["actual_sum"] = q["mean_actual"] * q["periods"]
        q["abs_error_sum"] = q["wape_pct"] / 100 * q["actual_sum"]
        q["error_sum"] = q["bias_pct"] / 100 * q["actual_sum"]
        q["part"] = i
        parts.append(q[["grain", "model", "part", "periods", "actual_sum", "abs_error_sum",
                        "error_sum"]])
    p = pd.concat(parts, ignore_index=True)
    g = p.groupby(["grain", "model"])
    out = g.agg(blocks=("part", "nunique"), periods=("periods", "sum"),
                actual_sum=("actual_sum", "sum"), abs_error_sum=("abs_error_sum", "sum"),
                error_sum=("error_sum", "sum")).reset_index()
    out = out[out["blocks"] == len(tables)].copy()
    out["wape_pct"] = 100 * out["abs_error_sum"] / out["actual_sum"]
    out["accuracy_pct"] = 100 - out["wape_pct"]
    out["bias_pct"] = 100 * out["error_sum"] / out["actual_sum"]
    out["block"] = label
    return out[["block", "grain", "model", "blocks", "periods", "accuracy_pct", "wape_pct",
                "bias_pct"]].sort_values(["grain", "wape_pct"]).reset_index(drop=True)


def select_validation_winners(metrics: pd.DataFrame, metric: str = "wape_pct") -> pd.DataFrame:
    """Select one model per grain using validation rows only; never inspect test scores."""
    if metric not in metrics:
        raise ValueError(f"unknown selection metric: {metric}")
    validation = metrics[(metrics["block"] == "validation") & metrics[metric].notna()].copy()
    if set(validation["grain"]) != {"daily", "weekly", "monthly"}:
        raise ValueError("validation metrics do not cover all grains")
    winners = validation.loc[validation.groupby("grain")[metric].idxmin()].copy()
    return winners.sort_values("grain").reset_index(drop=True)


def selected_final_metrics(metrics: pd.DataFrame, winners: pd.DataFrame) -> pd.DataFrame:
    """Reveal final-test scores only for models selected on validation data."""
    chosen = winners[["grain", "model"]].drop_duplicates()
    final = metrics[metrics["block"] == "test"].merge(chosen, on=["grain", "model"], how="inner")
    return final.sort_values("grain").reset_index(drop=True)


def score_performance_windows(
    frames: dict[str, dict[str, pd.DataFrame]],
    windows: dict[str, tuple[date, date]],
) -> pd.DataFrame:
    """Combine stored cow-period sufficient statistics without error cancellation."""
    rows = []
    for model, grains in frames.items():
        for grain, frame in grains.items():
            f = frame.copy()
            f["period_start"] = pd.to_datetime(f["period_start"])
            for block, (start, end) in windows.items():
                q = f[(f["period"] == "test")
                      & f["period_start"].between(pd.Timestamp(start), pd.Timestamp(end))]
                q = q.dropna(subset=["actual_sum", "abs_error_sum", "squared_error_sum"])
                rows.append({"block": block, "model": model, "grain": grain,
                             **_metrics_from_sums(q, grain)})
    columns = [c for c in METRIC_COLUMNS if c not in {"cows", "median_ape_pct"}]
    return (pd.DataFrame(rows)[columns].sort_values(["block", "grain", "model"])
            .reset_index(drop=True))


def winner_map(winners: pd.DataFrame) -> dict[str, set[str]]:
    """Convert validation winners to the restricted model/grain map used for final scoring."""
    out: dict[str, set[str]] = {}
    for row in winners[["model", "grain"]].itertuples(index=False):
        out.setdefault(row.model, set()).add(row.grain)
    return out


def to_frontend_backtest_rows(metrics: pd.DataFrame) -> pd.DataFrame:
    """Map cow-yield scores to BacktestRow-shaped experimental preview fields.

    The non-production series name deliberately prevents these rows being mistaken for
    herd-total ``milk_litres`` forecasts. They must not be inserted into ``c1_output``.
    """
    required = {"block", "model", "grain", "periods", "mae", "rmse", "bias"}
    missing = required - set(metrics.columns)
    if missing:
        raise ValueError(f"metrics missing frontend fields: {sorted(missing)}")
    out = metrics[list(required)].copy()
    out = out.rename(columns={"periods": "n_origins"})
    out["block"] = out["block"].map({"validation": "development", "test": "test"})
    out["grain"] = out["grain"].map({"daily": "day", "weekly": "week", "monthly": "month"})
    out["horizon"] = 1
    out["series"] = "milk_litres_per_cow_experiment"
    out["coverage"] = np.nan
    columns = ["block", "model", "grain", "horizon", "series", "mae", "rmse",
               "bias", "coverage", "n_origins"]
    return out[columns].sort_values(["grain", "mae", "model"]).reset_index(drop=True)


def plot_model_performance(model: str, frames: dict[str, pd.DataFrame],
                           output: Path | None = None,
                           show_test_grains: set[str] | None = None,
                           valid_start: date = VALID_START, test_start: date = TEST_START,
                           gap: tuple[date, date] | None = None):
    """Plot train/validation, revealing final test only for preselected grains.

    ``gap`` (a recording gap excluded from the experiment) is shaded and labelled.
    """
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=False)
    for ax, grain in zip(axes, ("daily", "weekly", "monthly")):
        if grain not in frames:
            ax.axis("off")
            continue
        f = frames[grain].copy()
        f["period_start"] = pd.to_datetime(f["period_start"])
        freq = {"daily": "D", "weekly": "W-MON", "monthly": "MS"}[grain]

        def with_explicit_gaps(block: str) -> pd.DataFrame:
            part = f[f["period"] == block].set_index("period_start").sort_index()
            if part.empty:
                return part
            # Matplotlib connects non-adjacent points. Reindexing inserts NaN at
            # missing periods so a 2021 point is never joined to a 2026 point.
            return part.reindex(pd.date_range(part.index.min(), part.index.max(), freq=freq))

        train = with_explicit_gaps("train")
        validation = with_explicit_gaps("validation")
        test = with_explicit_gaps("test")
        ax.plot(train.index, train["actual"], color="#3b3b3b", lw=1.1,
                label="Recorded training history")
        ax.plot(validation.index, validation["actual"], color="#3b3b3b", marker="o",
                markerfacecolor="white", ms=3, lw=0.9,
                label="Validation actual")
        ax.plot(validation.index, validation["prediction"], color="#d97706", ls="--",
                lw=1.3, label="Validation prediction")
        reveal = show_test_grains is None or grain in show_test_grains
        if reveal:
            ax.plot(test.index, test["actual"], color="#111827", marker="o",
                    markerfacecolor="white", ms=3, lw=0.9,
                    label="Final-test actual")
            ax.plot(test.index, test["prediction"], color="#1f77b4", ls="--",
                    lw=1.4, label="Final-test prediction")
            scored = test.dropna(subset=["actual", "prediction"])
            unavailable_from = (scored.index.max() if len(scored)
                                else pd.Timestamp(test_start))
            mode = (str(f["evaluation_mode"].dropna().iloc[0])
                    if "evaluation_mode" in f and f["evaluation_mode"].notna().any()
                    else "fixed_origin")
            if mode == "fixed_origin" and unavailable_from < pd.Timestamp(TEST_END):
                ax.axvspan(unavailable_from, pd.Timestamp(TEST_END), color="#9ca3af",
                           alpha=0.18, label="No fixed-origin eligible cow cohort")
                midpoint = unavailable_from + (pd.Timestamp(TEST_END) - unavailable_from) / 2
                ax.text(midpoint, 0.5, "No leakage-free\nindividual-cow score",
                        transform=ax.get_xaxis_transform(), ha="center", va="center",
                        fontsize=8, color="#4b5563")
            ax.set_xlim(pd.Timestamp(TRAIN_START), pd.Timestamp(TEST_END))
        if gap is not None:
            ax.axvspan(pd.Timestamp(gap[0]), pd.Timestamp(gap[1]), color="#fca5a5",
                       alpha=0.15, label="Recording gap (excluded)")
            ax.set_xlim(pd.Timestamp(TRAIN_START), pd.Timestamp(TEST_END))
        ax.axvline(pd.Timestamp(valid_start), color="#a16207", ls=":", lw=1)
        ax.axvline(pd.Timestamp(test_start), color="#4a6fa5", ls=":", lw=1)
        ax.set_title(f"{grain.capitalize()} mean yield per recorded cow-day",
                     loc="left", fontsize=10)
        ax.set_ylabel("litres / cow-day")
        ax.grid(alpha=0.25)
    handles, labels = axes[0].get_legend_handles_labels()
    if handles:
        axes[0].legend(handles, labels, loc="best", fontsize=8)
    fig.suptitle(f"Farm X — {model}: chronological validation and final test", fontsize=12)
    fig.tight_layout()
    if output is not None:
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output, dpi=170, bbox_inches="tight")
    return fig


def safe_input_summary(frame: pd.DataFrame) -> pd.DataFrame:
    """Year-level counts only; safe to display in the notebook."""
    out = (frame.assign(year=frame["date"].dt.year)
           .groupby(["year", "period"], as_index=False)
           .agg(cow_days=("litres", "size"), cows=("animal", "nunique"),
                days=("date", "nunique"), mean_litres=("litres", "mean"),
                fixed_origin_scoreable=("score_eligible", "sum")))
    assert not ({"animal", "cow_id", "animal_key"} & set(out.columns))
    return out


def safe_test_coverage_by_year(frame: pd.DataFrame,
                               test_start: date = TEST_START) -> pd.DataFrame:
    """Aggregate test availability, including years with zero eligible observations."""
    rows = []
    test = frame[frame["period"] == "test"].copy()
    for year in range(test_start.year, TEST_END.year + 1):
        part = test[test["date"].dt.year == year]
        eligible = part[part["score_eligible"]]
        observed = len(part)
        rows.append({
            "year": year,
            "observed_clean_cow_days": observed,
            "scoreable_cow_days": len(eligible),
            "scoreable_pct": 100.0 * len(eligible) / observed if observed else 0.0,
            "observed_cows": part["animal"].nunique(),
            "scoreable_cows": eligible["animal"].nunique(),
        })
    out = pd.DataFrame(rows)
    assert not ({"animal", "cow_id", "animal_key"} & set(out.columns))
    return out


def write_accuracy_outputs(metrics: pd.DataFrame,
                           frames: dict[str, dict[str, pd.DataFrame]], out: Path) -> list[Path]:
    """Write only aggregate score/plot frames."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    metrics = metrics.assign(model_version=COW_MODEL_VERSION, test_name=COW_TEST_NAME)
    metrics.to_csv(out / "metrics.csv", index=False)
    written.append(out / "metrics.csv")
    for model, grains in frames.items():
        for grain, frame in grains.items():
            assert not ({"animal", "cow_id", "animal_key"} & set(frame.columns))
            path = out / f"performance_{model}_{grain}.csv"
            frame.to_csv(path, index=False)
            written.append(path)
    return written
