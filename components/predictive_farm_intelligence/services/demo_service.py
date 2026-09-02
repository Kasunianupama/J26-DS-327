"""Deterministic synthetic data service used by the predictive prototype.

The service deliberately sits behind an API boundary: replacing this class with
a DelPro/database/model implementation does not require changing the frontend
contracts.  Values remain fictional and must not be treated as NLDB records.
"""
from __future__ import annotations

from datetime import date, timedelta
from math import exp, pi, sin
from random import Random


TODAY = date(2026, 8, 29)
DATA_THROUGH = date(2026, 8, 27)
GENERATED_AT = "2026-08-29T05:40:00+05:30"
HORIZONS = {
    "30d": 30,
    "90d": 90,
    "12m": 365,
    "18m": 548,
    "24m": 730,
    # Backward-compatible aliases for clients using the original API contract.
    "1y": 365,
    "2y": 730,
}

HORIZON_LABELS = {
    "30d": "30 days",
    "90d": "90 days",
    "12m": "12 months",
    "18m": "18 months",
    "24m": "24 months",
    "1y": "1 year",
    "2y": "2 years",
}

FARMS = (
    {"id": "FARM_01", "name": "Ridiyagama Farm", "populated": True},
    {"id": "FARM_02", "name": "Bopaththalawa Farm", "populated": False},
    {"id": "FARM_03", "name": "Ambewela Livestock", "populated": False},
)


def _round(value: float, digits: int = 1) -> float:
    return round(value, digits)


class PredictiveDemoService:
    """Read-only deterministic implementation of the predictive contracts."""

    def farms(self) -> list[dict]:
        return [dict(farm) for farm in FARMS]

    def _require_farm(self, farm_id: str) -> dict:
        farm = next((item for item in FARMS if item["id"] == farm_id), None)
        if farm is None:
            raise KeyError(farm_id)
        return farm

    def animals(self, farm_id: str) -> list[dict]:
        farm = self._require_farm(farm_id)
        if not farm["populated"]:
            return []
        random = Random(20260829)
        states = ["Milking"] * 145 + ["Dry"] * 42 + ["Heifer"] * 38 + ["Calf"] * 46 + ["Male / bull"] * 13
        groups = (
            "Imported Jersey (founder)", "F1 Jersey × Local", "F2 Jersey Cross",
            "F3 Jersey Cross", "Local / Indigenous", "Unknown parentage",
        )
        animals = []
        for index, state in enumerate(states):
            dim = random.randint(4, 303) if state == "Milking" else None
            current_yield = _round(11.5 + random.random() * 10.5 - ((dim or 0) / 305) * 3.2) if dim else 0.0
            pregnant = state == "Dry" or (state == "Milking" and (dim or 0) > 150 and random.random() < .6)
            expected_calving = TODAY + timedelta(days=random.randint(5, 150)) if pregnant else None
            animals.append({
                "id": f"LK-{2100 + index * 3:04d}",
                "ear_tag": str(1000 + index),
                "production_state": state,
                "genetic_group": groups[index % len(groups)],
                "days_in_milk": dim,
                "current_yield": current_yield,
                "pregnant": pregnant,
                "expected_calving": expected_calving.isoformat() if expected_calving else None,
                "conception_probability": _round(.42 + (index % 37) / 100, 2) if state in {"Milking", "Heifer"} else None,
                "health_events": 3 if index in {7, 31} else 1 if index % 41 == 0 else 0,
            })
        return animals

    @staticmethod
    def _day_point(offset: int) -> dict:
        current_date = TODAY + timedelta(days=offset)
        season = 1 + .035 * sin((current_date.month - 1) / 12 * 2 * pi)
        long_trend = offset * .12
        october_dip = 285 * exp(-((offset - 58) / 17) ** 2)
        recovery = 105 * exp(-((offset - 112) / 35) ** 2)
        expected = (2475 + long_trend - october_dip + recovery) * season
        milkers = round(145 - 13 * exp(-((offset - 58) / 18) ** 2) + 6 * exp(-((offset - 115) / 35) ** 2))
        confidence = "High" if offset <= 30 else "Moderate" if offset <= 90 else "Limited"
        width = 65 + max(0, offset) * .45
        return {
            "date": current_date.isoformat(), "offset": offset,
            "observed": _round(expected + ((offset * 17) % 31 - 15), 0) if offset <= -2 else None,
            "expected": _round(expected, 0) if offset > 0 else None,
            "lower": _round(max(0, expected - width), 0) if offset > 0 else None,
            "upper": _round(expected + width, 0) if offset > 0 else None,
            "milkers": milkers,
            "calvings": 1 if offset > 0 and offset % 17 == 0 else 0,
            "dry_offs": 1 if offset > 0 and 42 <= offset <= 75 and offset % 3 == 0 else 0,
            "transition_share": _round(min(.48, .08 + max(0, offset) / 1900), 3),
            "confidence": confidence,
            "thi": _round(72 + 3.5 * sin((current_date.month - 2) / 12 * 2 * pi)),
        }

    def timeline(self, farm_id: str, horizon: str = "90d") -> list[dict]:
        self._require_farm(farm_id)
        days = HORIZONS[horizon]
        return [self._day_point(offset) for offset in range(-30, days + 1)]

    def overview(self, farm_id: str, horizon: str = "90d") -> dict:
        points = [point for point in self.timeline(farm_id, horizon) if point["offset"] > 0]
        early, late = points[:7], points[-7:]
        mean = lambda values, key: sum(float(item[key] or 0) for item in values) / max(1, len(values))
        average = mean(points, "expected")
        average_per_cow = sum((point["expected"] or 0) / max(1, point["milkers"]) for point in points) / len(points)
        early_milk, late_milk = mean(early, "expected"), mean(late, "expected")
        low = min(points, key=lambda point: point["expected"] or float("inf"))
        confidence = "Limited" if any(point["confidence"] == "Limited" for point in points) else "Moderate" if any(point["confidence"] == "Moderate" for point in points) else "High"
        dry_offs = sum(point["dry_offs"] for point in points)
        entries = sum(point["calvings"] for point in points)
        step = max(1, len(points) // 40)
        return {
            "label": HORIZON_LABELS[horizon],
            "days": HORIZONS[horizon], "start_date": points[0]["date"], "end_date": points[-1]["date"],
            "average_daily_milk": _round(average, 1), "average_per_cow": _round(average_per_cow, 1),
            "early_milk": _round(early_milk, 1), "late_milk": _round(late_milk, 1),
            "change_percent": _round((late_milk - early_milk) / max(1, early_milk) * 100, 1),
            "dry_offs": dry_offs, "entries": entries, "net_movement": entries - dry_offs,
            "confidence": confidence,
            "low_point": {key: low[key] for key in ("date", "expected", "lower", "upper", "milkers", "confidence")},
            "margin_gap_lkr_thousands": -1840 if HORIZONS[horizon] >= 90 else -620,
            "spark": [point["expected"] for index, point in enumerate(points) if index % step == 0],
        }

    def findings(self, farm_id: str) -> list[dict]:
        self._require_farm(farm_id)
        return [
            {"id":"F1", "kind":"Forecast change", "severity":"critical", "title":"Milk capacity is expected to fall during the October transition window", "summary":"Expected dry-offs are only partly offset by likely lactation entries. The shortfall reaches product allocation and margin.", "confidence":"Moderate", "chain":[{"step":"Herd", "detail":"A concentrated dry-off window reduces the active milking group."},{"step":"Milk", "detail":"Expected daily milk reaches its lowest point in late October."},{"step":"Finance", "detail":"Lower product allocation places expected margin below budget."}], "links":[{"label":"Open the October window", "workspace":"future", "date":"2026-10-14"},{"label":"See which cows dry off", "workspace":"capacity", "tab":"milk", "date":"2026-10-14"},{"label":"Product and margin effect", "workspace":"commerce", "month":"2026-10"}]},
            {"id":"F2", "kind":"Action needed", "severity":"critical", "title":"Cows past 110 days in milk have no insemination on record", "summary":"This may indicate a recording gap or missed heats and can move future lactation entries outside the selected horizon.", "confidence":"High", "links":[{"label":"Open reproduction and capacity", "workspace":"capacity", "tab":"reproduction"}]},
            {"id":"F3", "kind":"Confidence change", "severity":"attention", "title":"November forecast confidence is limited", "summary":"A growing share of expected milk depends on transitions that have not happened yet.", "confidence":"Limited", "links":[{"label":"See what makes up November", "workspace":"future", "date":"2026-11-15"},{"label":"Evidence and coverage", "workspace":"evidence"}]},
            {"id":"F4", "kind":"Upcoming", "severity":"attention", "title":"Pregnancy checks fall due in the next three weeks", "summary":"Confirming these records will narrow the October forecast range.", "confidence":"High", "links":[{"label":"Open the capacity flow", "workspace":"capacity", "tab":"reproduction"}]},
            {"id":"F5", "kind":"Data limitation", "severity":"routine", "title":"Individual abortion prediction is unavailable", "summary":"Too few comparable historical events are available for an animal-level estimate.", "confidence":"Limited", "links":[{"label":"Model and data coverage", "workspace":"evidence"}]},
            {"id":"F6", "kind":"Opportunity", "severity":"routine", "title":"F3 Jersey cross animals hold their lactation curve longer", "summary":"The recorded cohort has a flatter post-peak curve than F1 animals.", "confidence":"Moderate", "links":[{"label":"Herd profile and genetics", "workspace":"capacity", "tab":"genetics"}]},
        ]

    def milk(self, farm_id: str, horizon: str = "90d") -> dict:
        overview = self.overview(farm_id, horizon)
        return {"farm_id": farm_id, "overview": overview, "timeline": self.timeline(farm_id, horizon), "source": "deterministic_synthetic_backend"}

    def reproduction(self, farm_id: str) -> dict:
        animals = self.animals(farm_id)
        return {"farm_id": farm_id, "pregnant": sum(bool(a["pregnant"]) for a in animals), "expected_calvings_90d": sum(bool(a["expected_calving"] and a["expected_calving"] <= (TODAY + timedelta(days=90)).isoformat()) for a in animals), "pregnancy_checks_due": 18, "services_per_conception": 1.84, "source": "deterministic_synthetic_backend"}

    def finance(self, farm_id: str, horizon: str = "90d") -> dict:
        overview = self.overview(farm_id, horizon)
        milk = overview["average_daily_milk"] * overview["days"]
        return {"farm_id": farm_id, "expected_milk_litres": _round(milk, 0), "expected_revenue_lkr_thousands": _round(milk * 158 / 1000, 0), "margin_gap_lkr_thousands": overview["margin_gap_lkr_thousands"], "tetra_pack_shortfall_litres": 6840 if overview["days"] >= 90 else 0, "source": "deterministic_synthetic_backend"}

    def evidence(self, farm_id: str) -> dict:
        self._require_farm(farm_id)
        return {"farm_id":farm_id, "generated_at":GENERATED_AT, "data_through":DATA_THROUGH.isoformat(), "coverage":[{"source":"Herd & animal records", "coverage":97, "through":"2026-08-27", "gaps":"11 animals with incomplete parentage"},{"source":"Milk recording", "coverage":94, "through":"2026-08-27", "gaps":"6–19 Feb 2026 meter fault"},{"source":"Reproduction events", "coverage":88, "through":"2026-08-26", "gaps":"Sparse heat observations before Mar 2025"},{"source":"Finance & budget", "coverage":99, "through":"2026-08-27", "gaps":"None material"}], "models":[{"id":"milk-yield", "name":"Individual lactation roll-forward", "status":"Active", "last_validated":"2026-08-27"},{"id":"abortion", "name":"Abortion risk", "status":"Reduced", "last_validated":"2026-08-20"}], "source":"deterministic_synthetic_backend"}

    def animal(self, farm_id: str, animal_id: str) -> dict | None:
        return next((animal for animal in self.animals(farm_id) if animal["id"] == animal_id.upper()), None)

    def snapshot(self, farm_id: str, horizon: str = "90d") -> dict:
        farm = self._require_farm(farm_id)
        return {"farm":dict(farm), "farms":self.farms(), "generated_at":GENERATED_AT, "data_through":DATA_THROUGH.isoformat(), "horizon":horizon, "overview":self.overview(farm_id, horizon), "findings":self.findings(farm_id), "workspaces":{"milk":self.milk(farm_id, horizon)["overview"], "reproduction":self.reproduction(farm_id), "finance":self.finance(farm_id, horizon), "evidence":self.evidence(farm_id)}, "source":"deterministic_synthetic_backend", "data_notice":"All values are fictional synthetic prototype data."}


predictive_demo_service = PredictiveDemoService()
