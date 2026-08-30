"""Typed contract for forecast context consumed by the reasoning component.

This contract intentionally separates a forecast from a recommendation.  The
Digital Agronomist may translate the context into follow-up work, but must not
present a forecast or an association as a clinical diagnosis.
"""

from typing import Literal

from pydantic import BaseModel, Field


ForecastConfidence = Literal["High", "Moderate", "Limited"]
EvidenceSource = Literal["Individual", "Individual + peer", "Peer", "Herd", "Historical only"]


class ForecastRange(BaseModel):
    expected: float = Field(ge=0)
    lower: float = Field(ge=0)
    upper: float = Field(ge=0)


class ForecastDrivers(BaseModel):
    milkers: int = Field(ge=0)
    calvings: int = Field(ge=0)
    dry_offs: int = Field(ge=0)
    transition_share: float = Field(ge=0, le=1)
    thi: float | None = Field(default=None, ge=0)


class PriorityAnimal(BaseModel):
    animal_id: str
    reason: str
    evidence: EvidenceSource
    conception_probability: float | None = Field(default=None, ge=0, le=1)
    health_events: int = Field(default=0, ge=0)


class PredictiveFinding(BaseModel):
    id: str
    title: str
    severity: Literal["critical", "attention", "routine"]
    summary: str


class PredictiveFarmContext(BaseModel):
    """Farm-level outlook supplied by Predictive Farm Intelligence."""

    farm_id: str
    forecast_window_days: int = Field(ge=1, le=730)
    milk_litres_per_day: ForecastRange
    drivers: ForecastDrivers
    confidence: ForecastConfidence
    priority_animals: list[PriorityAnimal] = Field(default_factory=list)
    findings: list[PredictiveFinding] = Field(default_factory=list)
    source: str = "predictive_farm_intelligence"
