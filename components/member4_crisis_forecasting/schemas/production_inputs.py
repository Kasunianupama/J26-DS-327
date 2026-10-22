"""Proposed historical production boundary; no database mapping or I/O."""

from typing import Literal

from pydantic import Field

from components.member4_crisis_forecasting.schemas.daily_inputs import DailyRiskInput


class ProductionDay(DailyRiskInput):
    """Daily per-cow actuals; source is provenance, milk_source is measurement origin."""

    milk_source: Literal["shipment", "delpro"] | None = None
    target_litres_per_cow: float | None = Field(default=None, ge=0, allow_inf_nan=False, strict=True)
    is_scoreable: bool = Field(strict=True)
