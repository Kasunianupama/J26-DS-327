from contextlib import contextmanager
from datetime import date

import pytest

from components.member1_didt.services.farmx_repository import (
    AnimalNotFound, FarmXDataUnavailable, FarmXRepository,
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


def test_repository_builds_current_state_without_filling_missing_data():
    engine = FakeEngine(row())
    state = FarmXRepository(engine).get_current_state("SYNTH-DB-1")
    assert engine.connection.params == {"animal_ref": "SYNTH-DB-1"}
    assert state.milk_yield_l_day == 21.5
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
