"""Origin-safe health, treatment and lagged-sensor features for the cow-yield models.

Every feature for cow-day *t* uses only facts dated strictly before *t*. A feature family
has three states, never a bare null:

- ``available``: the source table holds records in that calendar year and the value is
  real (a count of 0 means no event was recorded for this cow);
- ``missing``: the source is recorded that year but this cow has no prior value (sensors);
- ``unavailable``: the source table has fewer than ``min_records`` records that year, so
  the absence of events says nothing about the cow.

Each family is encoded as numeric value(s) filled with 0, plus ``<family>_available`` and
``<family>_unavailable`` 0/1 flags, so one frozen model adapts to the recording regime.
A ``<family>_status`` text column is kept for aggregate profiling only. Every family is
measured at a per-row forecast origin (see ``add_event_features``), so weekly and monthly
forecasts use only what was known when the week or month began.

Event-level inputs carry only the per-run ``cow_id`` integer, never a pseudonym key.
Categorical labels (health group, diagnosis, treatment name) are one-hot counted for the
most frequent training-period labels; the rest fall into ``other``.
"""
from __future__ import annotations

import re
from datetime import date

import numpy as np
import pandas as pd

from .data import _IDENT

WINDOW_DAYS = 30
LONG_WINDOW_DAYS = 365
DAYS_SINCE_CAP = 400.0
TOP_LABELS = 8
MIN_LABEL_COUNT = 20
# A source year with fewer records than this is "unavailable": a handful of records in a
# herd of about 2,000 cows means the source was not being kept, not that cows were healthy.
DEFAULT_MIN_RECORDS = 100
# The same treatment given to at least this many cows on one day is a herd campaign
# (vaccination, preventive dosing), not a sign that an individual cow was ill.
CAMPAIGN_MIN_COWS = 20
# Sensor columns with fewer non-null values than this share, or a single distinct value,
# carry no information and are dropped (reported in ``frame.attrs["dropped_sensors"]``).
MIN_SENSOR_SHARE = 0.01
SENSOR_COLUMNS = ("milkings", "conductivity", "milking_duration_sec", "avg_blood",
                  "avg_cell_count", "avg_bcs", "avg_weight", "avg_rectal_temp")
_KEY = 100_000  # combined (cow, day) key; day numbers since 1970 stay below this


def _cow_map_ctes(core: str) -> str:
    """The same eligible target set and cow numbering as ``cow_accuracy_sql``."""
    return f"""
    target_raw AS MATERIALIZED (
        SELECT d.animal_key, d.milk_date, COUNT(*) AS n_records
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
    ), cow_map AS MATERIALIZED (
        SELECT animal_key, DENSE_RANK() OVER (ORDER BY animal_key) AS cow_id
        FROM (SELECT DISTINCT animal_key FROM target_raw WHERE n_records = 1) k
    )"""


def health_events_sql(core: str) -> str:
    """One row per health episode of a modelled cow; no pseudonym key is returned."""
    if not _IDENT.match(core):
        raise ValueError(f"invalid schema name: {core!r}")
    return f"""
    WITH {_cow_map_ctes(core)}
    SELECT m.cow_id, h.start_date AS event_date,
           COALESCE(h.health_group, 'unspecified') AS health_group,
           COALESCE(h.diagnosis_group, 'unspecified') AS diagnosis_group,
           COALESCE(h.category, 'unspecified') AS category,
           COALESCE(h.diagnosis_name, 'unspecified') AS diagnosis_name,
           h.milk_withhold_end_date
    FROM {core}.health_episode h
    JOIN cow_map m ON m.animal_key = h.animal_key
    WHERE h.start_date IS NOT NULL
      AND h.start_date BETWEEN CAST(:start AS date) - 400 AND CAST(:end AS date)"""


def treatment_events_sql(core: str) -> str:
    """One row per treatment record of a modelled cow; no pseudonym key is returned."""
    if not _IDENT.match(core):
        raise ValueError(f"invalid schema name: {core!r}")
    return f"""
    WITH {_cow_map_ctes(core)}
    SELECT m.cow_id, th.treatment_start_date AS event_date,
           th.duration_in_days::float AS duration_days,
           COALESCE(th.treatment_name, 'unspecified') AS treatment_name,
           COALESCE(th.diagnosis_name, 'unspecified') AS diagnosis_name,
           th.diverted_milk::float AS diverted_milk
    FROM {core}.treatment_history th
    JOIN cow_map m ON m.animal_key = th.animal_key
    WHERE th.treatment_start_date IS NOT NULL
      AND NOT COALESCE(th.is_bad_date, false)
      AND NOT COALESCE(th.is_unlinked_animal, false)
      AND th.treatment_start_date BETWEEN CAST(:start AS date) - 400 AND CAST(:end AS date)"""


def source_availability_sql(core: str) -> str:
    """Whole-table record counts per calendar year (aggregate only)."""
    if not _IDENT.match(core):
        raise ValueError(f"invalid schema name: {core!r}")
    return f"""
    SELECT 'health_episode' AS source, EXTRACT(YEAR FROM start_date)::int AS year,
           COUNT(*)::int AS records
    FROM {core}.health_episode
    WHERE start_date IS NOT NULL
    GROUP BY 2
    UNION ALL
    SELECT 'treatment_history', EXTRACT(YEAR FROM treatment_start_date)::int, COUNT(*)::int
    FROM {core}.treatment_history
    WHERE treatment_start_date IS NOT NULL AND NOT COALESCE(is_bad_date, false)
    GROUP BY 2
    ORDER BY 1, 2"""


def load_event_inputs(source, start: date, end: date
                      ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Health events, treatment events and yearly source availability (read-only)."""
    health = source._q(health_events_sql(source.core), start=start, end=end)
    treatments = source._q(treatment_events_sql(source.core), start=start, end=end)
    availability = source._q(source_availability_sql(source.core))
    for name, frame in (("health", health), ("treatments", treatments)):
        if {"animal_key", "record_key", "episode_key", "group_key"} & set(frame.columns):
            raise ValueError(f"{name} events must not contain source keys")
    return health, treatments, availability


def _slug(label: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", str(label).strip().lower()).strip("_")
    return s[:40] or "unspecified"


def _day_number(dates) -> np.ndarray:
    return (pd.to_datetime(dates).to_numpy().astype("datetime64[D]").astype(np.int64))


def _keys(cows, dates) -> np.ndarray:
    return np.asarray(cows, dtype=np.int64) * _KEY + _day_number(dates)


def _count_before(event_keys: np.ndarray, row_keys: np.ndarray, window: int) -> np.ndarray:
    """Events with day in [t - window, t - 1] for the same cow."""
    ev = np.sort(event_keys)
    return (np.searchsorted(ev, row_keys, "left")
            - np.searchsorted(ev, row_keys - window, "left")).astype(float)


def _days_since(event_keys: np.ndarray, row_keys: np.ndarray) -> np.ndarray:
    out = np.full(len(row_keys), DAYS_SINCE_CAP)
    ev = np.sort(event_keys)
    if not len(ev):
        return out
    idx = np.searchsorted(ev, row_keys, "left") - 1
    ok = idx >= 0
    prev = ev[np.clip(idx, 0, None)]
    same_cow = ok & (prev // _KEY == row_keys // _KEY)
    out[same_cow] = np.minimum(row_keys[same_cow] - prev[same_cow], DAYS_SINCE_CAP)
    return out


def _active(start_keys: np.ndarray, end_keys: np.ndarray, row_keys: np.ndarray) -> np.ndarray:
    """Intervals that started before t and end on or after t (end known at start)."""
    starts, ends = np.sort(start_keys), np.sort(end_keys)
    return (np.searchsorted(starts, row_keys, "left")
            - np.searchsorted(ends, row_keys, "left")).clip(min=0).astype(float)


def _top_labels(events: pd.DataFrame, column: str, train_end: date) -> list[str]:
    """Most frequent labels in training-period events only, so the test never chooses them."""
    if events.empty or column not in events:
        return []
    train = events[pd.to_datetime(events["event_date"]) <= pd.Timestamp(train_end)]
    counts = train[column].astype(str).value_counts()
    return list(counts[counts >= MIN_LABEL_COUNT].index[:TOP_LABELS])


def yearly_availability(availability: pd.DataFrame, source: str,
                        min_records: int = DEFAULT_MIN_RECORDS) -> dict[int, bool]:
    a = availability[availability["source"] == source]
    return {int(y): int(r) >= min_records for y, r in zip(a["year"], a["records"])}


def _year_status(origins: pd.Series, by_year: dict[int, bool]) -> np.ndarray:
    """Recording regime in the year of the last day known at the origin."""
    years = (pd.to_datetime(origins) - pd.Timedelta(days=1)).dt.year.to_numpy()
    return np.array([by_year.get(int(y), False) for y in years])


def _set_family(f: pd.DataFrame, family: str, values: dict[str, np.ndarray],
                available: np.ndarray, unavailable: np.ndarray) -> list[str]:
    """Write value columns (0 unless available), flags and a text status."""
    for name, v in values.items():
        f[name] = np.where(available, v, 0.0)
    f[f"{family}_available"] = available.astype(float)
    f[f"{family}_unavailable"] = unavailable.astype(float)
    f[f"{family}_status"] = np.select([available, unavailable],
                                      ["available", "unavailable"], "missing")
    return list(values) + [f"{family}_available", f"{family}_unavailable"]


def _last_value_before(f: pd.DataFrame, column: str, origins: pd.Series,
                       max_age_days: int = WINDOW_DAYS) -> np.ndarray:
    """The cow's latest non-null ``column`` dated strictly before its origin (or NaN)."""
    x = pd.to_numeric(f[column], errors="coerce")
    right = (pd.DataFrame({"animal": f["animal"].to_numpy(), "value_date": f["date"].to_numpy(),
                           "value": x.to_numpy()})
             .dropna(subset=["value"]).sort_values("value_date"))
    left = pd.DataFrame({"row": np.arange(len(f)), "animal": f["animal"].to_numpy(),
                         "origin": pd.to_datetime(origins).to_numpy()}).sort_values("origin")
    if right.empty:
        return np.full(len(f), np.nan)
    m = pd.merge_asof(left, right, left_on="origin", right_on="value_date", by="animal",
                      allow_exact_matches=False,
                      tolerance=pd.Timedelta(days=max_age_days))
    return m.sort_values("row")["value"].to_numpy(dtype=float)


def add_event_features(f: pd.DataFrame, health: pd.DataFrame | None,
                       treatments: pd.DataFrame | None,
                       availability: pd.DataFrame | None, train_end: date,
                       origins: pd.Series | None = None,
                       min_records: int = DEFAULT_MIN_RECORDS) -> tuple[pd.DataFrame, list[str]]:
    """Add the health, treatment, sensor-lag and THI-lag families to a prepared frame.

    ``f`` holds one row per cow-day with ``animal`` (per-run integer) and ``date``.
    ``origins`` is, per row, the issue date of the forecast: only facts dated strictly
    before it are used (default: the row's own date, a one-day-ahead forecast). Counts
    and active flags are measured at the origin; ``days_since_*`` runs to the target day.
    Labels for one-hot counts are chosen from events up to ``train_end`` only.
    Returns the frame and the numeric model feature names.
    """
    f = f.copy()
    origins = pd.to_datetime(f["date"] if origins is None else origins)
    origins = pd.Series(origins.to_numpy(), index=f.index)
    origin_keys = _keys(f["animal"], origins)
    horizon = (f["date"] - origins).dt.days.to_numpy(dtype=float)
    availability = (availability if availability is not None
                    else pd.DataFrame(columns=["source", "year", "records"]))
    features: list[str] = []

    def clean(events: pd.DataFrame | None) -> pd.DataFrame:
        if events is None or events.empty:
            return pd.DataFrame(columns=["cow_id", "event_date"])
        e = events.copy()
        e["event_date"] = pd.to_datetime(e["event_date"])
        return e[e["cow_id"].notna() & e["event_date"].notna()]

    def since(keys: np.ndarray) -> np.ndarray:
        return np.minimum(_days_since(keys, origin_keys) + horizon, DAYS_SINCE_CAP)

    def one_hot(events, keys, values, columns):
        for column, prefix in columns:
            top = _top_labels(events, column, train_end)
            if not top:
                continue
            labels = events[column].astype(str)
            for label in top:
                values[f"{prefix}_{_slug(label)}_30d"] = _count_before(
                    keys[(labels == label).to_numpy()], origin_keys, WINDOW_DAYS)
            values[f"{prefix}_other_30d"] = _count_before(
                keys[(~labels.isin(top)).to_numpy()], origin_keys, WINDOW_DAYS)

    # Health episodes -------------------------------------------------------------
    h = clean(health)
    h_ok = _year_status(origins, yearly_availability(availability, "health_episode",
                                                     min_records))
    hk = _keys(h["cow_id"], h["event_date"]) if len(h) else np.array([], dtype=np.int64)
    group = h["health_group"].astype(str).str.lower() if len(h) else pd.Series(dtype=str)
    mastitis = hk[group.str.contains("mastitis").to_numpy()] if len(h) else hk
    values = {
        "health_episodes_30d": _count_before(hk, origin_keys, WINDOW_DAYS),
        "health_episodes_365d": _count_before(hk, origin_keys, LONG_WINDOW_DAYS),
        "days_since_health_episode": since(hk),
        "mastitis_episodes_30d": _count_before(mastitis, origin_keys, WINDOW_DAYS),
        "mastitis_episodes_365d": _count_before(mastitis, origin_keys, LONG_WINDOW_DAYS),
        "days_since_mastitis": since(mastitis),
        "milk_withhold_active": np.zeros(len(f)),
    }
    if len(h) and "milk_withhold_end_date" in h:
        w = h.dropna(subset=["milk_withhold_end_date"])
        ends = pd.to_datetime(w["milk_withhold_end_date"])
        ends = ends.where(ends >= w["event_date"], w["event_date"])
        values["milk_withhold_active"] = _active(
            _keys(w["cow_id"], w["event_date"]), _keys(w["cow_id"], ends), origin_keys)
    one_hot(h, hk, values, (("health_group", "hg"), ("diagnosis_group", "dg"),
                            ("category", "hc"), ("diagnosis_name", "dx")))
    features += _set_family(f, "health", values, h_ok, ~h_ok)

    # Treatments ------------------------------------------------------------------
    t = clean(treatments)
    t_ok = _year_status(origins, yearly_availability(availability, "treatment_history",
                                                     min_records))
    tk = _keys(t["cow_id"], t["event_date"]) if len(t) else np.array([], dtype=np.int64)
    campaign = treatment_campaign_flags(t)
    individual = tk[~campaign] if len(t) else tk
    values = {
        "treatments_30d": _count_before(tk, origin_keys, WINDOW_DAYS),
        "treatments_365d": _count_before(tk, origin_keys, LONG_WINDOW_DAYS),
        "days_since_treatment": since(tk),
        "individual_treatments_30d": _count_before(individual, origin_keys, WINDOW_DAYS),
        "individual_treatments_365d": _count_before(individual, origin_keys, LONG_WINDOW_DAYS),
        "days_since_individual_treatment": since(individual),
        "campaign_treatments_30d": _count_before(tk[campaign] if len(t) else tk,
                                                 origin_keys, WINDOW_DAYS),
        "diverted_milk_treatments_30d": np.zeros(len(f)),
        "treatment_active": np.zeros(len(f)),
    }
    if len(t):
        diverted = pd.to_numeric(t.get("diverted_milk"), errors="coerce").fillna(0) > 0
        values["diverted_milk_treatments_30d"] = _count_before(
            tk[diverted.to_numpy()], origin_keys, WINDOW_DAYS)
        duration = pd.to_numeric(t.get("duration_days"), errors="coerce").fillna(1).clip(1, 120)
        ends = t["event_date"] + pd.to_timedelta(duration - 1, unit="D")
        values["treatment_active"] = _active(tk, _keys(t["cow_id"], ends), origin_keys)
    one_hot(t, tk, values, (("treatment_name", "tx"), ("diagnosis_name", "txdx")))
    features += _set_family(f, "treatment", values, t_ok, ~t_ok)

    # Sensor values: the cow's latest value before the origin (never the target day) --
    dropped = []
    for column in SENSOR_COLUMNS:
        if column not in f:
            continue
        x = pd.to_numeric(f[column], errors="coerce")
        # Production inference adds future cow-days (no records): judge the sensor on the
        # recorded rows only, exactly as Notebook 6 saw them.
        recorded = x[~f["is_future"].astype(bool)] if "is_future" in f else x
        if recorded.notna().mean() < MIN_SENSOR_SHARE or recorded.nunique(dropna=True) <= 1:
            dropped.append(column)
            continue
        by_year = {int(y): True for y in f.loc[x.notna(), "date"].dt.year.unique()}
        year_ok = _year_status(origins, by_year)
        prev = _last_value_before(f, column, origins)
        present = ~np.isnan(prev) & year_ok
        features += _set_family(f, f"{column}_prev", {f"{column}_prev": np.nan_to_num(prev)},
                                present, ~year_ok)

    # Weather: THI of the day before the origin (herd-level, known at issue time) ------
    if "thi_mean" in f:
        thi = (f.assign(thi=pd.to_numeric(f["thi_mean"], errors="coerce"))
               .groupby("date")["thi"].first().dropna())
        prev_day = thi.reindex(pd.DatetimeIndex(origins) - pd.Timedelta(days=1)).to_numpy(
            dtype=float)
        year_ok = _year_status(origins, {int(y): True for y in thi.index.year.unique()})
        present = ~np.isnan(prev_day) & year_ok
        features += _set_family(f, "thi_prev_day", {"thi_prev_day": np.nan_to_num(prev_day)},
                                present, ~year_ok)
    f.attrs["dropped_sensors"] = dropped
    return f, features


def treatment_campaign_flags(treatments: pd.DataFrame,
                             min_cows: int = CAMPAIGN_MIN_COWS) -> np.ndarray:
    """True for records of a treatment given to ``min_cows`` or more cows on one day."""
    if treatments is None or treatments.empty:
        return np.zeros(0, dtype=bool)
    day = pd.to_datetime(treatments["event_date"]).dt.normalize()
    name = (treatments["treatment_name"].astype(str) if "treatment_name" in treatments
            else pd.Series("unspecified", index=treatments.index))
    cows = treatments.groupby([day, name])["cow_id"].transform("nunique")
    return (cows >= min_cows).to_numpy()


def treatment_campaign_summary(treatments: pd.DataFrame) -> pd.DataFrame:
    """Records per year split into herd campaigns and individual treatments (aggregate)."""
    if treatments is None or treatments.empty:
        return pd.DataFrame(columns=["year", "campaign_records", "individual_records"])
    campaign = treatment_campaign_flags(treatments)
    year = pd.to_datetime(treatments["event_date"]).dt.year
    out = pd.DataFrame({"year": year, "campaign": campaign}).groupby("year").agg(
        campaign_records=("campaign", "sum"), all_records=("campaign", "size"))
    out["individual_records"] = out["all_records"] - out["campaign_records"]
    return out.drop(columns="all_records").reset_index()


_FAMILY_PREFIXES = (
    ("treatment", ("treatment", "days_since_treatment", "days_since_individual",
                   "individual_treatments", "campaign_treatments", "diverted_milk",
                   "tx_", "txdx_")),
    ("level", ("herd_", "cow_resid", "cow_vs_herd", "cow_level")),
    ("health", ("health", "mastitis", "days_since_health", "days_since_mastitis",
                "milk_withhold", "hg_", "dg_", "hc_", "dx_")),
    ("thi_prev_day", ("thi_",)),
)


def feature_family(feature: str) -> str:
    """``health``, ``treatment``, ``thi_prev_day`` or ``sensor`` for a model feature."""
    for family, prefixes in _FAMILY_PREFIXES:
        if feature.startswith(prefixes):
            return family
    return "sensor"


def availability_by_year(frame: pd.DataFrame) -> pd.DataFrame:
    """Share of cow-days per year in each status for every feature family (aggregate)."""
    status_cols = [c for c in frame.columns if c.endswith("_status")]
    rows = []
    year = frame["date"].dt.year
    for column in status_cols:
        counts = pd.crosstab(year, frame[column])
        for y, r in counts.iterrows():
            total = r.sum()
            rows.append({"family": column.removesuffix("_status"), "year": int(y),
                         **{f"{k}_pct": 100.0 * r.get(k, 0) / total
                            for k in ("available", "missing", "unavailable")}})
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["status"] = np.select([out["available_pct"] > 0, out["missing_pct"] > 0],
                              ["available", "missing"], "unavailable")
    return out.sort_values(["family", "year"]).reset_index(drop=True)


def synthetic_events(cows: pd.DataFrame, seed: int = 17
                     ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """SYNTHETIC fictional health and treatment events for the notebook's synthetic run.

    ``cows``: frame with ``cow_id`` and ``date``. Recording stops after 2021, so later
    years exercise the ``unavailable`` state. Not shaped from Farm X records.
    """
    rng = np.random.default_rng(seed)
    d = cows[pd.to_datetime(cows["date"]).dt.year.between(2015, 2021)]
    pick = d.sample(frac=0.004, random_state=seed) if len(d) else d
    health = pd.DataFrame({
        "cow_id": pick["cow_id"].to_numpy(),
        "event_date": pd.to_datetime(pick["date"]).to_numpy(),
        "health_group": rng.choice(["mastitis", "udder_teat", "preventive", "other"],
                                   len(pick), p=[0.5, 0.2, 0.2, 0.1]),
        "diagnosis_group": "synthetic_group",
        "category": "synthetic_category",
        "diagnosis_name": rng.choice(["synthetic_dx_a", "synthetic_dx_b"], len(pick)),
    })
    health["milk_withhold_end_date"] = health["event_date"] + pd.to_timedelta(4, unit="D")
    treatments = pd.DataFrame({
        "cow_id": health["cow_id"], "event_date": health["event_date"],
        "duration_days": 3.0,
        "treatment_name": rng.choice(["synthetic_tx_a", "synthetic_tx_b", "unspecified"],
                                     len(health)),
        "diagnosis_name": health["diagnosis_name"],
        "diverted_milk": rng.integers(0, 2, len(health)).astype(float),
    })
    years = list(range(2015, 2022))
    availability = pd.concat([
        pd.DataFrame({"source": "health_episode", "year": years,
                      "records": [int((health["event_date"].dt.year == y).sum()) for y in years]}),
        pd.DataFrame({"source": "treatment_history", "year": years,
                      "records": [int((treatments["event_date"].dt.year == y).sum()) for y in years]}),
    ], ignore_index=True)
    return health, treatments, availability
