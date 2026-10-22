"""C3-owned tool boundaries; C2 fields are provisional, not a producer contract."""
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

ToolName = Literal['core_summary', 'c1_forecast', 'c2_simulation', 'c4_risk']


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class ToolCall(Contract):
    tool: ToolName
    arguments: dict = Field(default_factory=dict)


class CoreArguments(Contract):
    topic: Literal['herd', 'weather']


class ForecastArguments(Contract):
    model_version: Literal['pfoi-1.2.0-dev'] = 'pfoi-1.2.0-dev'
    reference_date: date
    origin_date: date | None = None
    target_period: date
    grain: Literal['daily', 'weekly', 'monthly']
    series: Literal['herd_milk', 'n_herd', 'milking', 'calvings', 'dry_offs', 'real_abortions']

    @model_validator(mode='after')
    def dates_are_consistent(self):
        if self.origin_date is not None and (self.origin_date > self.reference_date or self.target_period < self.origin_date):
            raise ValueError('Forecast dates conflict.')
        return self


class SimulationArguments(Contract):
    # Proposed C3 request only: the C2 owner must confirm supported scenarios/units.
    intervention: str = Field(min_length=1, max_length=100)
    change_percent: FiniteFloat
    horizon_days: int = Field(strict=True, ge=1, le=730)


class BaseEvidence(Contract):
    demo: bool
    core_version: str = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


class CoreEvidence(BaseEvidence):
    kind: Literal['core_summary'] = 'core_summary'
    topic: Literal['herd', 'weather']
    observed_date: date
    metrics: dict[Literal['total_animals', 'milking', 'dry', 'mean_daily_thi', 'max_hourly_thi'], FiniteFloat | None]


class ForecastEvidence(BaseEvidence):
    kind: Literal['c1_forecast'] = 'c1_forecast'
    model_version: str
    origin_date: date
    target_period: date
    grain: Literal['daily', 'weekly', 'monthly']
    series: str
    forecast: FiniteFloat
    lower: FiniteFloat | None = None
    upper: FiniteFloat | None = None
    quality_flags: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def validate_bounds(self):
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            raise ValueError('Reversed bounds.')
        return self


class SimulationEvidence(BaseEvidence):
    kind: Literal['c2_simulation'] = 'c2_simulation'
    model_version: str = Field(min_length=1)
    intervention: str
    change_percent: FiniteFloat
    horizon_days: int = Field(strict=True, ge=1, le=730)
    baseline_litres: FiniteFloat = Field(ge=0)
    simulated_litres: FiniteFloat = Field(ge=0)
    assumptions: list[str] = Field(min_length=1)


class RiskArguments(Contract):
    reference_date: date
    purpose: Literal['historical_explanation', 'live_warning'] = 'historical_explanation'


class RiskEvidence(Contract):
    """C4's historical export has no core_version field; never infer one locally."""
    kind: Literal['c4_risk'] = 'c4_risk'
    demo: bool
    source: Literal['c4_output.farm_risk_assessment_v1'] = 'c4_output.farm_risk_assessment_v1'
    contract_version: Literal['1.1.0']
    score_basis: str = Field(min_length=1)
    scoring_version: str = Field(min_length=1)
    model_status: str = Field(min_length=1)
    research_only: bool = Field(strict=True)
    live_warning_allowed: bool = Field(strict=True)
    reference_date: date
    assessment_date: date
    assessment_cutoff: datetime | None = None
    generated_at: datetime | None = None
    source_core_version: None = None
    assessment_count: int = Field(strict=True, ge=1)
    climate_score: FiniteFloat | None = None
    biological_score: FiniteFloat | None = None
    operational_score: FiniteFloat | None = None
    combined_score: FiniteFloat | None = None
    warnings: list[str] = Field(default_factory=list)

Evidence = Annotated[CoreEvidence | ForecastEvidence | SimulationEvidence | RiskEvidence, Field(discriminator='kind')]


class ToolOutcome(Contract):
    status: Literal['success', 'needs_input', 'invalid_request', 'unavailable', 'error', 'invalid_result']
    tool: ToolName | None = None
    message: str
    missing_fields: list[str] = Field(default_factory=list)
    evidence: Evidence | None = None
