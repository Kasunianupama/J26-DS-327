from contextlib import contextmanager
from datetime import date, datetime

import pytest

from components.member1_didt.services.farmx_repository import (
    AnimalNotFound, AVAILABLE_ANIMALS_SQL, CURRENT_STATE_SQL,
    SELECTED_RECORD_QUALITY_SQL, FarmXDataUnavailable, FarmXRepository,
)


class FakeResult:
    def __init__(self, row): self.row = row
    def mappings(self): return self
    def first(self): return self.row
    def all(self): return [] if self.row is None else [self.row]


class FakeConnection:
    def __init__(self, row): self.row, self.params = row, None
    def execute(self, statement, params):
        self.params = params
        return FakeResult(self.row)


class FakeEngine:
    def __init__(self, row): self.connection = FakeConnection(row)
    @contextmanager
    def connect(self): yield self.connection


def row(**updates):
    data = {"animal_ref": "SYNTH-DB-1", "observed_date": date(2026, 1, 2),
            "breed": "Synthetic fixture", "age_days": 1300, "lactation_no": 2,
            "days_in_milk": 100, "days_pregnant": None, "milk_yield_l_day": 21.5,
            "milkings_per_day": 2, "dry_matter_intake": None, "concentrate_intake": None,
            "bcs": 3.0, "body_weight": 500, "rectal_temperature": 38.4,
            "thi_mean": 70.0, "n_calvings": 2, "recent_clinical_event_count": 0,
            "recent_treatment_count": 0}
    data.update(updates)
    return data


def daily_record(record_date, *, animal_key="cow-a", record_key="row-1", **updates):
    data = {
        "animal_key": animal_key,
        "record_key": record_key,
        "observed_date": record_date,
        "milkings": 2,
    }
    data.update(updates)
    return data


def body_measurement(measure_date, *, animal_key="cow-a", record_key="measure-1",
                    weight=500, measure_type="weight", bad_date=False,
                    unlinked=False, event_ts=None):
    return {
        "animal_key": animal_key,
        "record_key": record_key,
        "event_date": measure_date,
        "event_ts": event_ts if event_ts is not None else (
            datetime.combine(measure_date, datetime.min.time()) if measure_date is not None else None
        ),
        "measure_type": measure_type,
        "weight": weight,
        "is_bad_date": bad_date,
        "is_unlinked_animal": unlinked,
    }


def select_scenario_records(records):
    """Fixture reference: filter eligible records first, then select one per key."""
    eligible = [
        record for record in records
        if record["animal_key"] is not None
        and date(2026, 1, 1) <= record["observed_date"] < date(2027, 1, 1)
        and record["milkings"] is not None and record["milkings"] > 0
    ]
    selected = {}
    for record in eligible:
        key = record["animal_key"]
        current = selected.get(key)
        # ETL defines core.daily_milk.record_key as unique; it is the stable
        # same-date tie-breaker used by both production queries.
        if current is None or record["observed_date"] > current["observed_date"] or (
            record["observed_date"] == current["observed_date"]
            and record["record_key"] < current["record_key"]
        ):
            selected[key] = record
    return selected


def select_latest_body_weight(measurements, animal_key):
    """Synthetic reference for the current-state query's body-measure selector."""
    valid = [
        item for item in measurements
        if item["animal_key"] == animal_key
        and item["measure_type"] == "weight"
        and item["event_date"] is not None
        and item["weight"] is not None and 0 < item["weight"] < float("inf")
        and not item["is_bad_date"] and not item["is_unlinked_animal"]
    ]
    valid.sort(key=lambda item: item["record_key"])
    valid.sort(key=lambda item: (item["event_ts"] is not None,
                                 item["event_ts"] or datetime.min), reverse=True)
    valid.sort(key=lambda item: item["event_date"], reverse=True)
    return valid[0] if valid else None


def test_repository_builds_current_state_without_filling_missing_data():
    engine = FakeEngine(row())
    state = FarmXRepository(engine).get_current_state("SYNTH-DB-1")
    assert engine.connection.params == {"animal_ref": "SYNTH-DB-1"}
    assert state.milk_yield_l_day == 21.5
    assert state.body_weight == 500
    assert state.dry_matter_intake is None
    assert any("source unit is undocumented" in message for message in state.data_limitations)


def test_repository_missing_animal_and_database_error_are_safe():
    with pytest.raises(AnimalNotFound):
        FarmXRepository(FakeEngine(None)).get_current_state("absent")

    class FailedEngine:
        @contextmanager
        def connect(self):
            raise RuntimeError("sensitive driver detail")
            yield

    with pytest.raises(FarmXDataUnavailable) as caught:
        FarmXRepository(FailedEngine()).get_current_state("SYNTH-DB-1")
    assert "sensitive" not in str(caught.value)


def test_repository_lists_bounded_references_without_exposing_other_fields():
    engine = FakeEngine({"animal_ref": "SYNTH-DB-1", "observed_date": date(2026, 1, 2)})
    records = FarmXRepository(engine).list_available_animals(limit=1)
    assert engine.connection.params == {"limit": 1}
    assert records[0].animal_ref == "SYNTH-DB-1"
    assert records[0].observed_date == "2026-01-02"
    with pytest.raises(ValueError):
        FarmXRepository(engine).list_available_animals(limit=0)


def test_scenario_population_sql_filters_before_ranking_and_uses_record_key_tie_break():
    current_sql = str(CURRENT_STATE_SQL)
    listing_sql = str(AVAILABLE_ANIMALS_SQL)
    for query in (current_sql, listing_sql):
        normalized = " ".join(query.split())
        assert "with eligible_records as" in normalized
        assert "row_number() over" in normalized
        assert "source_row.milk_date >= date '2026-01-01'" in normalized
        assert "source_row.milk_date < date '2027-01-01'" in normalized
        assert "source_row.milkings > 0" in normalized
        assert "order by source_row.milk_date desc, source_row.record_key asc" in normalized
        assert "max(milk_date)" not in normalized
    assert "source_row.animal_key=:animal_ref" in " ".join(current_sql.split())
    # The state query keeps the previous quality gate after selecting its
    # latest positive-milking candidate.
    quality = " ".join(SELECTED_RECORD_QUALITY_SQL.split())
    assert quality in " ".join(current_sql.split())
    assert "yield_litres is not null" in quality
    assert "is_spike" in quality and "is_bad_date" in quality
    assert "dim is not null" in quality


def test_current_state_gets_latest_valid_body_measurement_independently():
    normalized = " ".join(str(CURRENT_STATE_SQL).split())
    assert "bm.weight as body_weight" in normalized
    assert "from core.body_measure measure" in normalized
    assert "measure.animal_key=d.animal_key" in normalized
    assert "measure.measure_type='weight'" in normalized
    assert "measure.weight > 0" in normalized
    assert "measure.weight < 'Infinity'::double precision" in normalized
    assert "measure.event_date is not null" in normalized
    assert "coalesce(measure.is_bad_date,true)=false" in normalized
    assert "coalesce(measure.is_unlinked_animal,true)=false" in normalized
    assert "order by measure.event_date desc, measure.event_ts desc nulls last, measure.record_key asc" in normalized
    assert "measure.event_date=d.milk_date" not in normalized
    assert "measure.event_date >= date '2026-01-01'" not in normalized
    assert "measure.event_date < date '2027-01-01'" not in normalized


def test_latest_body_weight_is_independent_of_selected_milk_date_and_cow():
    milk_rows = [
        daily_record(date(2026, 6, 10), animal_key="cow-a", record_key="milk-a"),
        daily_record(date(2026, 6, 10), animal_key="cow-b", record_key="milk-b"),
    ]
    selected_milk = select_scenario_records(milk_rows)
    assert selected_milk["cow-a"]["record_key"] == "milk-a"

    measurements = [
        body_measurement(date(2026, 5, 1), animal_key="cow-a", record_key="before", weight=510),
        body_measurement(date(2026, 7, 1), animal_key="cow-a", record_key="after", weight=520),
        body_measurement(date(2026, 6, 1), animal_key="cow-b", record_key="cow-b-before", weight=480),
        body_measurement(date(2026, 8, 1), animal_key="cow-a", record_key="cow-a-newer", weight=530),
    ]
    assert select_latest_body_weight(measurements, "cow-a")["weight"] == 530
    assert select_latest_body_weight(measurements, "cow-b")["weight"] == 480
    assert selected_milk["cow-a"]["record_key"] == "milk-a"
    assert selected_milk["cow-a"]["observed_date"] == date(2026, 6, 10)


def test_latest_body_weight_uses_latest_measurement_and_stable_same_date_tie_break():
    measurements = [
        body_measurement(date(2026, 3, 1), record_key="older", weight=500),
        body_measurement(date(2026, 4, 1), record_key="same-z", weight=510,
                         event_ts=datetime(2026, 4, 1, 9)),
        body_measurement(date(2026, 4, 1), record_key="same-a", weight=515,
                         event_ts=datetime(2026, 4, 1, 9)),
        body_measurement(date(2026, 4, 1), record_key="later-time", weight=520,
                         event_ts=datetime(2026, 4, 1, 10)),
    ]
    selected = select_latest_body_weight(measurements, "cow-a")
    assert selected["record_key"] == "later-time"
    tied = [item for item in measurements if item["event_ts"] == datetime(2026, 4, 1, 9)]
    assert select_latest_body_weight(tied, "cow-a")["record_key"] == "same-a"


def test_body_weight_missing_when_no_valid_measurement_exists():
    measurements = [
        body_measurement(date(2026, 4, 1), measure_type="bcs", weight=500),
        body_measurement(date(2026, 4, 2), record_key="bad-date", bad_date=True),
        body_measurement(date(2026, 4, 3), record_key="unlinked", unlinked=True),
        body_measurement(date(2026, 4, 4), record_key="null-weight", weight=None),
        body_measurement(date(2026, 4, 5), record_key="zero-weight", weight=0),
        body_measurement(None, record_key="missing-date", weight=500),
    ]
    assert select_latest_body_weight(measurements, "cow-a") is None
    state = FarmXRepository(FakeEngine(row(body_weight=None))).get_current_state("SYNTH-DB-1")
    assert state.body_weight is None
    assert any("no valid measurement" in message for message in state.data_limitations)


def test_latest_positive_milking_record_selected_per_cow():
    rows = [
        daily_record(date(2026, 1, 2), record_key="a-1"),
        daily_record(date(2026, 4, 3), record_key="a-2"),
        daily_record(date(2026, 2, 5), animal_key="cow-b", record_key="b-1"),
    ]
    selected = select_scenario_records(rows)
    assert selected["cow-a"]["record_key"] == "a-2"
    assert selected["cow-b"]["record_key"] == "b-1"


@pytest.mark.parametrize("latest_milkings", [0, None])
def test_falls_back_to_latest_positive_record_when_newer_record_is_ineligible(latest_milkings):
    rows = [
        daily_record(date(2026, 3, 1), record_key="earlier", milkings=2),
        daily_record(date(2026, 5, 1), record_key="later", milkings=latest_milkings),
    ]
    selected = select_scenario_records(rows)
    assert selected["cow-a"]["record_key"] == "earlier"


def test_excludes_cows_without_positive_milking_record_in_2026():
    rows = [
        daily_record(date(2026, 2, 1), animal_key="zero", milkings=0),
        daily_record(date(2026, 3, 1), animal_key="null", milkings=None),
        daily_record(date(2025, 12, 31), animal_key="prior", milkings=2),
        daily_record(date(2027, 1, 1), animal_key="future", milkings=2),
    ]
    assert select_scenario_records(rows) == {}


def test_population_count_matches_distinct_reference_eligibility():
    rows = [
        daily_record(date(2026, 1, 2), animal_key="cow-a", record_key="a1"),
        daily_record(date(2026, 4, 2), animal_key="cow-a", record_key="a2"),
        daily_record(date(2026, 2, 2), animal_key="cow-b", record_key="b1"),
        daily_record(date(2026, 3, 2), animal_key="cow-c", milkings=0, record_key="c1"),
        daily_record(date(2025, 12, 31), animal_key="cow-d", record_key="d1"),
    ]
    selected = select_scenario_records(rows)
    reference_count = len({
        row["animal_key"] for row in rows
        if row["animal_key"] is not None
        and date(2026, 1, 1) <= row["observed_date"] < date(2027, 1, 1)
        and row["milkings"] is not None and row["milkings"] > 0
    })
    assert len(selected) == reference_count == 2
    assert len({record["animal_key"] for record in selected.values()}) == len(selected)


def test_duplicate_latest_date_uses_unique_stable_record_key():
    rows = [
        daily_record(date(2026, 4, 1), record_key="row-z", milkings=2),
        daily_record(date(2026, 4, 1), record_key="row-a", milkings=3),
    ]
    assert select_scenario_records(rows)["cow-a"]["record_key"] == "row-a"
