"""API contracts for the Predictive Farm Intelligence workspace."""
from typing import Any, Literal

from pydantic import BaseModel, Field


HorizonId = Literal["30d", "90d", "12m", "18m", "24m", "1y", "2y"]
Confidence = Literal["High", "Moderate", "Limited"]


class PredictiveFarm(BaseModel):
    id: str
    name: str
    populated: bool


class PredictiveLowPoint(BaseModel):
    date: str
    expected: float = Field(ge=0)
    lower: float = Field(ge=0)
    upper: float = Field(ge=0)
    milkers: int = Field(ge=0)
    confidence: Confidence


class PredictiveOverview(BaseModel):
    label: str
    days: int = Field(ge=1, le=730)
    start_date: str
    end_date: str
    average_daily_milk: float = Field(ge=0)
    average_per_cow: float = Field(ge=0)
    early_milk: float = Field(ge=0)
    late_milk: float = Field(ge=0)
    change_percent: float
    dry_offs: int = Field(ge=0)
    entries: int = Field(ge=0)
    net_movement: int
    confidence: Confidence
    low_point: PredictiveLowPoint
    margin_gap_lkr_thousands: float
    spark: list[float]


class PredictiveFindingLink(BaseModel):
    label: str
    workspace: Literal["future", "capacity", "commerce", "evidence"]
    tab: Literal["milk", "reproduction", "genetics"] | None = None
    date: str | None = None
    month: str | None = None
    animalId: str | None = None


class PredictiveFindingChain(BaseModel):
    step: str
    detail: str


class PredictiveWorkspaceFinding(BaseModel):
    id: str
    kind: Literal["Action needed", "Upcoming", "Forecast change", "Data limitation", "Opportunity", "Confidence change"]
    severity: Literal["critical", "attention", "routine"]
    title: str
    summary: str
    confidence: Confidence
    chain: list[PredictiveFindingChain] | None = None
    links: list[PredictiveFindingLink]


class PredictiveSnapshot(BaseModel):
    farm: PredictiveFarm
    farms: list[PredictiveFarm]
    generated_at: str
    data_through: str
    horizon: HorizonId
    overview: PredictiveOverview
    findings: list[PredictiveWorkspaceFinding]
    workspaces: dict[str, Any]
    source: Literal["deterministic_synthetic_backend"]
    data_notice: str
