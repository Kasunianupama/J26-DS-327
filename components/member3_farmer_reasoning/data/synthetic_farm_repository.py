"""Member 3 farm records aligned to Member 2's deterministic herd dataset.

Member 2 is the source for the prototype's farm shape: its date basis is
2026-08-29, it contains 284 animals, and its tags begin at LK-2100 / 1000.
This adapter keeps the smaller Member 3 record contract while using the same
population mix and operational groups, so the two components no longer tell
stories about different farms.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from random import Random


# Matches frontend/src/data/component2/core.ts.
TODAY = date(2026, 8, 29)


@dataclass(frozen=True)
class Animal:
    animal_id: str
    ear_tag: str
    breed: str
    group: str
    status: str
    pregnant: bool
    expected_calving: date | None
    days_in_milk: int | None
    current_yield: float = 0.0


_GROUPS = (
    ("Imported Jersey (founder)", 0.05),
    ("F1 Jersey × Local", 0.21),
    ("F2 Jersey Cross", 0.28),
    ("F3 Jersey Cross", 0.24),
    ("Local / Indigenous", 0.14),
    ("Unknown parentage", 0.08),
)


def _choose_group(random: Random) -> str:
    point = random.random()
    cumulative = 0.0
    for name, share in _GROUPS:
        cumulative += share
        if point <= cumulative:
            return name
    return _GROUPS[-1][0]


def _build_animals() -> tuple[Animal, ...]:
    """Create the Member 2 population categories with stable Member 3 fields."""
    random = Random(20260829)
    # The distribution is the documented Member 2 mix: 145 + 42 + 38 + 46 + 13.
    states = ("lactating",) * 145 + ("dry",) * 42 + ("heifer",) * 38 + ("calf",) * 46 + ("bull",) * 13
    animals: list[Animal] = []
    for index, status in enumerate(states):
        animal_id = f"LK-{2100 + index * 3:04d}"
        ear_tag = str(1000 + index)
        breed = _choose_group(random)
        days_in_milk = random.randint(4, 303) if status == "lactating" else None
        pregnant = status == "dry" or (status == "lactating" and days_in_milk > 150 and random.random() < 0.6) or (status == "heifer" and random.random() < 0.3)
        expected_calving = TODAY + timedelta(days=random.randint(5, 150)) if pregnant else None
        group = (
            "Shed 1 — high yield" if status == "lactating" and days_in_milk < 100
            else "Shed 2 — mid lactation" if status == "lactating" and days_in_milk < 210
            else "Shed 3 — late lactation" if status == "lactating"
            else "Dry & transition" if status in {"dry", "bull"}
            else "Youngstock"
        )
        yield_litres = round(11.5 + random.random() * 10.5 - ((days_in_milk or 0) / 305) * 3.2, 1) if status == "lactating" else 0.0
        animals.append(Animal(animal_id, ear_tag, breed, group, status, pregnant, expected_calving, days_in_milk, yield_litres))
    return tuple(animals)


ANIMALS = _build_animals()


class SyntheticFarmDataRepository:
    """Read-only Member 3 view of the same prototype population as Member 2."""

    farm_id = "FARM_01"
    farm_name = "Ruhunu Farm"

    def animals(self, farm_id: str) -> list[Animal]:
        return list(ANIMALS) if farm_id == self.farm_id else []

    def animal(self, farm_id: str, token: str) -> Animal | None:
        wanted = token.upper().replace("_", "-")
        return next((animal for animal in self.animals(farm_id) if animal.animal_id == wanted or animal.ear_tag == token.zfill(4)), None)

    def milk_records(self, farm_id: str, animal_id: str | None = None, days: int = 30) -> list[dict]:
        records: list[dict] = []
        for animal in self.animals(farm_id):
            if animal.status != "lactating" or (animal_id and animal.animal_id != animal_id):
                continue
            # Stable day-to-day variation around Member 2-compatible current yield.
            seed = sum(ord(char) for char in animal.animal_id)
            for offset in range(days - 1, -1, -1):
                variation = ((seed + offset * 7) % 9 - 4) * 0.14
                taper = max(0, (animal.days_in_milk or 0) - 235) * 0.008
                value = max(4.0, animal.current_yield + variation - taper)
                records.append({"record_id": f"MILK-{animal.ear_tag}-{offset}", "animal_id": animal.animal_id, "date": TODAY - timedelta(days=offset), "milk_litres": round(value, 1)})
        return records

    def health_events(self, farm_id: str, animal_id: str | None = None) -> list[dict]:
        # Current review signals are deliberately separate from diagnoses.
        events = [
            {"record_id": "HLT-1007-01", "animal_id": "LK-2121", "date": TODAY - timedelta(days=4), "event": "Elevated somatic-cell-count review", "severity": "high", "status": "follow-up required"},
            {"record_id": "HLT-1031-01", "animal_id": "LK-2193", "date": TODAY - timedelta(days=10), "event": "Reduced feed-intake observation", "severity": "medium", "status": "monitoring"},
            {"record_id": "HLT-1058-01", "animal_id": "LK-2274", "date": TODAY - timedelta(days=18), "event": "Lameness observation", "severity": "medium", "status": "treated"},
        ]
        return [event for event in events if not animal_id or event["animal_id"] == animal_id] if farm_id == self.farm_id else []

    def feed_decision(self, farm_id: str) -> dict | None:
        if farm_id != self.farm_id:
            return None
        return {"record_id": "DEC-001", "date": TODAY - timedelta(days=14), "group": "Shed 2 — mid lactation", "change": "Increase concentrate by 0.5 kg/cow/day", "baseline_litres": 15.8, "after_litres": 16.4, "added_cost_lkr": 1840, "milk_price_lkr": 145}
