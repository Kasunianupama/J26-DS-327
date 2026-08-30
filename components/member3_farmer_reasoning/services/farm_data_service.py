"""Approved deterministic operations over the current Member 3 data source."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from components.member3_farmer_reasoning.data.synthetic_farm_repository import SyntheticFarmDataRepository, TODAY


class FarmDataService:
    def __init__(self, repository: SyntheticFarmDataRepository | None = None): self.repository = repository or SyntheticFarmDataRepository()

    def herd_summary(self, farm_id: str) -> dict:
        animals = self.repository.animals(farm_id)
        return {"total": len(animals), "lactating": sum(a.status == "lactating" for a in animals), "dry": sum(a.status == "dry" for a in animals), "pregnant": sum(a.pregnant for a in animals)}

    def attention_animals(self, farm_id: str) -> list[dict]:
        items = []
        for event in self.repository.health_events(farm_id):
            items.append({"animal_id": event["animal_id"], "priority": event["severity"], "reason": event["event"], "record_id": event["record_id"]})
        return sorted(items, key=lambda item: {"high": 0, "medium": 1}.get(item["priority"], 2))

    def animal_history(self, farm_id: str, animal_id: str) -> dict | None:
        animal = self.repository.animal(farm_id, animal_id)
        if not animal: return None
        records = self.repository.milk_records(farm_id, animal.animal_id)
        first, latest = records[0]["milk_litres"], records[-1]["milk_litres"] if records else (None, None)
        return {"animal": animal, "milk": records, "first": first, "latest": latest, "health": self.repository.health_events(farm_id, animal.animal_id)}

    def next_month_calvings(self, farm_id: str) -> list[dict]:
        end = TODAY + timedelta(days=31)
        return [{"animal_id": a.animal_id, "expected_calving": a.expected_calving.isoformat()} for a in self.repository.animals(farm_id) if a.expected_calving and TODAY <= a.expected_calving <= end]

    def weekly_production(self, farm_id: str) -> dict:
        records = self.repository.milk_records(farm_id, days=14)
        split = TODAY - timedelta(days=6)
        current = sum(r["milk_litres"] for r in records if r["date"] >= split)
        previous = sum(r["milk_litres"] for r in records if r["date"] < split)
        return {"current": round(current, 1), "previous": round(previous, 1), "change_pct": round((current - previous) / previous * 100, 1)}

    def group_production(self, farm_id: str) -> list[dict]:
        groups: dict[str, list[float]] = defaultdict(list)
        animals = {a.animal_id: a for a in self.repository.animals(farm_id)}
        for record in self.repository.milk_records(farm_id, days=7): groups[animals[record["animal_id"]].group].append(record["milk_litres"])
        return [{"group": group, "average_litres": round(sum(values) / len(values), 1)} for group, values in groups.items()]

    def feed_change_impact(self, farm_id: str) -> dict | None:
        decision = self.repository.feed_decision(farm_id)
        if not decision: return None
        daily_gain = decision["after_litres"] - decision["baseline_litres"]
        group_size = sum(
            animal.status == "lactating" and animal.group == decision["group"]
            for animal in self.repository.animals(farm_id)
        )
        added_revenue = daily_gain * group_size * decision["milk_price_lkr"]
        return {**decision, "group_size": group_size, "daily_gain_litres": round(daily_gain * group_size, 1), "daily_net_lkr": round(added_revenue - decision["added_cost_lkr"], 0)}
