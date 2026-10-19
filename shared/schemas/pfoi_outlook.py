"""Contract for Component 1 (PFOI) outlook outputs, as stored in schema c1_output.

Teammates restore c1_output from a dump and read it through these models. The columns
are a contract: change them only with a CONTRACT_VERSION bump and a note in
shared/schemas/PFOI_OUTLOOK_CHANGES.md. All values are herd-level aggregates (no animal
keys). ``source`` says whether a response holds model output or labelled demo data.
"""
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

CONTRACT_VERSION = "1.0"

Grain = Literal["daily", "weekly", "monthly"]
OutlookSeries = Literal["herd_milk", "n_herd", "milking", "calvings", "dry_offs", "real_abortions"]
DataSource = Literal["model", "demo"]


class OutlookRow(BaseModel):
    """One forecast: herd_milk in litres per period; milking and n_herd as mean animals;
    calvings, dry_offs, real_abortions as counts per period."""

    origin_date: date
    target_period: date = Field(description="first day of the forecast period")
    grain: Grain
    horizon: int = Field(ge=1)
    series: OutlookSeries
    forecast: float
    lower: float | None = Field(default=None, description="5 % empirical bound")
    upper: float | None = Field(default=None, description="95 % empirical bound")
    quality_flag: str = Field(description="ok | low_recording | source_switch | k_window (; separated)")
    model_version: str
    core_version: str | None = None


class AttributionRow(BaseModel):
    """One additive part of a change: milk factors (litres/day) add up to the model change;
    with 'residual' (past months) to the actual change. Herd flows add up to the stock change."""

    origin_date: date
    target_period: date
    grain: Grain
    series: str
    factor: str
    contribution: float | None
    kind: Literal["past", "forecast"]
    model_version: str
    core_version: str | None = None


class HistoryRow(BaseModel):
    origin_date: date
    period: date
    grain: Grain
    series: str
    actual: float | None = Field(description="null when the period is not scoreable")
    quality_flag: Literal["ok", "partial", "gap"]
    model_version: str
    core_version: str | None = None


class OutlookResponse(BaseModel):
    source: DataSource
    contract_version: str = CONTRACT_VERSION
    origin_date: date | None
    model_version: str | None
    core_version: str | None
    outlook: list[OutlookRow]
    history: list[HistoryRow]


class AttributionResponse(BaseModel):
    source: DataSource
    contract_version: str = CONTRACT_VERSION
    origin_date: date | None
    attribution: list[AttributionRow]
