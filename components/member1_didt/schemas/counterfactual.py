"""Versioned request and response contracts for counterfactual simulation."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CowState(BaseModel):
    """Latest approved measured cow-day; unavailable measurements stay null."""
    model_config = ConfigDict(extra="forbid")

    animal_ref: str = Field(min_length=1, max_length=160)
    observed_date: str | None = None
    breed: str | None = None
    age_days: int | None = Field(default=None, ge=0)
    parity: int | None = Field(default=None, ge=0)
    lactation_no: int | None = Field(default=None, ge=0)
    days_in_milk: int | None = Field(default=None, ge=0)
    days_pregnant: int | None = Field(default=None, ge=0)
    milk_yield_l_day: float | None = Field(default=None, ge=0)
    milkings_per_day: float | None = Field(default=None, ge=0)
    dry_matter_intake: float | None = Field(default=None, ge=0)
    concentrate_intake: float | None = Field(default=None, ge=0)
    bcs: float | None = Field(default=None, ge=1, le=5)
    body_weight: float | None = Field(default=None, gt=0)
    rectal_temperature: float | None = None
    thi_mean: float | None = None
    n_calvings: int | None = Field(default=None, ge=0)
    recent_clinical_event_count: int | None = Field(default=None, ge=0)
    recent_treatment_count: int | None = Field(default=None, ge=0)
    data_limitations: list[str] = Field(default_factory=list)


class CowReference(BaseModel):
    """Approved animal reference available for simulator selection."""
    animal_ref: str
    observed_date: str


class InterventionScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str | None = Field(default=None, max_length=120)
    category: Literal["feed", "supplement", "heat", "management"]
    name: str = Field(min_length=1, max_length=120)
    feature: Literal["dry_matter_intake", "concentrate_intake", "thi_mean", "milkings_per_day"]
    proposed_value: float = Field(allow_inf_nan=False)
    unit: str = Field(min_length=1, max_length=40)
    intervention_description: str = Field(default="", max_length=400)


class SimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    animal_ref: str = Field(min_length=1, max_length=160)
    prediction_horizon_days: int = Field(default=1, ge=1, le=1)
    # Each row is one independently simulated alternative; limit is intentional.
    scenarios: list[InterventionScenario] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def unique_scenario_ids(self):
        ids = [scenario.scenario_id for scenario in self.scenarios if scenario.scenario_id]
        if len(ids) != len(set(ids)):
            raise ValueError("Scenario identifiers must be unique within a request.")
        return self


class ScenarioEstimate(BaseModel):
    scenario_id: str
    category: str
    name: str
    intervention_description: str = ""
    feature: str
    scenario_status: Literal[
        "ESTIMATED_MODEL_INPUT_PERTURBATION",
        "UNSUPPORTED_INTERVENTION_SEMANTICS",
        "BASELINE_FEATURE_UNAVAILABLE",
        "OUTSIDE_TRAINING_SUPPORT",
        "PREDICTION_UNAVAILABLE",
    ]
    baseline_value: float | None = None
    proposed_value: float
    unit: str
    change_applied: float | None = None
    baseline_predicted_milk_yield_l_day: float | None = None
    counterfactual_predicted_milk_yield_l_day: float | None = None
    absolute_yield_change_l_day: float | None = None
    percentage_yield_change: float | None = None
    model_version: str | None = None
    estimate_type: str = "model_based_counterfactual_estimate"
    assumptions: list[str] = Field(default_factory=list)
    data_limitations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SimulationResponse(BaseModel):
    contract_version: str = "1.0"
    animal_ref: str
    observed_date: str | None = None
    observed_milk_yield_l_day: float | None = None
    cow_state: CowState
    prediction_horizon_days: int
    baseline_status: Literal["AVAILABLE", "UNAVAILABLE"]
    baseline_predicted_milk_yield_l_day: float | None = None
    model_version: str | None = None
    scenarios: list[ScenarioEstimate]
    warnings: list[str] = Field(default_factory=list)
