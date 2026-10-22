"""Synthetic-only tests for origin-safe health, treatment and sensor-lag features."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.cow_events import (
    add_event_features,
    availability_by_year,
    health_events_sql,
    source_availability_sql,
    synthetic_events,
    treatment_campaign_flags,
    treatment_events_sql,
)


def frame() -> pd.DataFrame:
    dates = pd.date_range("2019-12-25", "2020-01-10", freq="D")
    rows = [{"animal": cow, "date": d, "thi_mean": 70.0 + i, "conductivity": 5.0 + i,
             "milkings": np.nan}
            for cow in (1, 2) for i, d in enumerate(dates)]
    return pd.DataFrame(rows)


def events():
    health = pd.DataFrame({
        "cow_id": [1, 1], "event_date": pd.to_datetime(["2020-01-03", "2019-12-26"]),
        "health_group": ["mastitis", "preventive"], "diagnosis_group": "g",
        "category": "c", "diagnosis_name": "d",
        "milk_withhold_end_date": pd.to_datetime(["2020-01-06", pd.NaT]),
    })
    treatments = pd.DataFrame({
        "cow_id": [1], "event_date": pd.to_datetime(["2020-01-03"]), "duration_days": [3.0],
        "treatment_name": ["unspecified"], "diagnosis_name": ["d"], "diverted_milk": [1.0],
    })
    availability = pd.DataFrame({"source": ["health_episode", "treatment_history"],
                                 "year": [2020, 2020], "records": [150, 0]})
    return health, treatments, availability


def at(f, cow, day):
    return f[(f["animal"] == cow) & (f["date"] == pd.Timestamp(day))].iloc[0]


def test_event_sql_returns_no_pseudonym_key_and_rejects_bad_schema():
    for sql in (health_events_sql("core"), treatment_events_sql("core")):
        select = sql.rsplit("SELECT m.cow_id", 1)[1].split("FROM", 1)[0]
        assert "animal_key" not in select
        assert "DENSE_RANK() OVER (ORDER BY animal_key)" in sql
    assert "NOT COALESCE(th.is_unlinked_animal, false)" in treatment_events_sql("core")
    assert "COUNT(*)" in source_availability_sql("core")
    with pytest.raises(ValueError):
        health_events_sql("core; drop")


def test_events_count_strictly_before_the_day():
    health, treatments, availability = events()
    f, features = add_event_features(frame(), health, treatments, availability,
                                     train_end=date(2019, 12, 31))
    assert at(f, 1, "2020-01-03")["mastitis_episodes_30d"] == 0  # same day is not used
    assert at(f, 1, "2020-01-04")["mastitis_episodes_30d"] == 1
    assert at(f, 1, "2020-01-04")["days_since_mastitis"] == 1
    assert at(f, 1, "2020-01-04")["milk_withhold_active"] == 1
    assert at(f, 1, "2020-01-07")["milk_withhold_active"] == 0
    assert at(f, 2, "2020-01-04")["mastitis_episodes_30d"] == 0
    assert "mastitis_episodes_30d" in features and "health_available" in features
    assert f[features].notna().all().all()


def test_years_without_records_are_unavailable_not_zero_events():
    health, treatments, availability = events()
    f, _ = add_event_features(frame(), health, treatments, availability,
                              train_end=date(2019, 12, 31))
    # 2019 has no health records at all; 2020 does.
    assert at(f, 1, "2019-12-30")["health_status"] == "unavailable"
    assert at(f, 1, "2019-12-30")["health_unavailable"] == 1
    assert at(f, 1, "2020-01-04")["health_status"] == "available"
    # Treatment table has 0 records in 2020: the recorded course is not trusted as signal.
    assert (f["treatment_status"] == "unavailable").all()
    assert (f["treatments_30d"] == 0).all()
    table = availability_by_year(f)
    row = table[(table["family"] == "health") & (table["year"] == 2019)].iloc[0]
    assert row["status"] == "unavailable" and row["unavailable_pct"] == 100


def test_sensor_and_weather_use_previous_values_only():
    f, features = add_event_features(frame(), None, None, None, train_end=date(2019, 12, 31))
    cow = f[f["animal"] == 1].reset_index(drop=True)
    assert cow.loc[0, "conductivity_prev_status"] == "missing"
    assert cow.loc[1, "conductivity_prev"] == cow.loc[0, "conductivity"]
    assert cow.loc[1, "thi_prev_day"] == cow.loc[0, "thi_mean"]
    assert "milkings_prev" not in f  # an all-empty sensor is dropped, not a dead feature
    assert f.attrs["dropped_sensors"] == ["milkings"]
    assert "conductivity_prev_available" in features


def test_fixed_origin_ignores_events_after_origin():
    health, treatments, availability = events()
    base = frame()
    origins = base["date"].where(base["date"] <= "2019-12-31", pd.Timestamp("2020-01-01"))
    f, _ = add_event_features(base, health, treatments, availability,
                              train_end=date(2019, 12, 31), origins=origins)
    assert at(f, 1, "2020-01-05")["mastitis_episodes_30d"] == 0
    assert at(f, 1, "2020-01-05")["conductivity_prev"] == at(f, 1, "2019-12-31")["conductivity"]
    # The origin's last known day is in 2019, which had no health records: unavailable.
    assert at(f, 1, "2020-01-05")["health_status"] == "unavailable"


def test_synthetic_events_stop_after_2021():
    cows = pd.DataFrame({"cow_id": np.repeat(np.arange(1, 50), 400),
                         "date": np.tile(pd.date_range("2018-01-01", periods=400, freq="7D"), 49)})
    health, treatments, availability = synthetic_events(cows)
    assert health["event_date"].dt.year.max() <= 2021
    assert set(availability["source"]) == {"health_episode", "treatment_history"}


def test_sparse_source_year_is_unavailable_by_default():
    health, treatments, availability = events()
    sparse = availability.assign(records=[5, 0])
    f, _ = add_event_features(frame(), health, treatments, sparse,
                              train_end=date(2019, 12, 31))
    assert (f["health_status"] == "unavailable").all()
    f, _ = add_event_features(frame(), health, treatments, sparse,
                              train_end=date(2019, 12, 31), min_records=1)
    assert at(f, 1, "2020-01-04")["health_status"] == "available"


def test_same_day_herd_treatment_is_a_campaign_not_an_individual_treatment():
    day = pd.Timestamp("2020-01-02")
    treatments = pd.DataFrame({
        "cow_id": list(range(1, 26)) + [1], "event_date": [day] * 25 + [day],
        "treatment_name": ["vaccine_x"] * 25 + ["therapy_y"],
        "diagnosis_name": "d", "duration_days": 1.0, "diverted_milk": 0.0,
    })
    flags = treatment_campaign_flags(treatments)
    assert flags[:25].all() and not flags[25]
    availability = pd.DataFrame({"source": ["treatment_history"], "year": [2020],
                                 "records": [500]})
    f, _ = add_event_features(frame(), None, treatments, availability,
                              train_end=date(2019, 12, 31))
    row = at(f, 1, "2020-01-03")
    assert row["campaign_treatments_30d"] == 1
    assert row["individual_treatments_30d"] == 1
    assert at(f, 2, "2020-01-03")["individual_treatments_30d"] == 0
