"""Historical supervised labels only. Never use future actuals as features."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from components.member4_crisis_forecasting.schemas.production_inputs import ProductionDay


def comparison_dates(origin: date) -> tuple[date, ...]:
    """Seven past dates, separately eligible origin, then seven future dates."""
    return tuple(origin + timedelta(days=offset) for offset in range(-7, 8))


def decline_statistics(past_values, future_values, config):
    """Shared arithmetic for point-in-time and explicitly retrospective targets."""
    past = sum(Decimal(str(value)) for value in past_values) / 7
    ahead = sum(Decimal(str(value)) for value in future_values) / 7
    if past <= 0:
        return None
    pct = (ahead - past) / past * 100
    return float(past), float(ahead), float(pct), pct <= -Decimal(str(config.decline_threshold_pct))


class DeclineTargetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decline_threshold_pct: float = Field(gt=0, le=100, allow_inf_nan=False)


class HistoricalLabelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    days: tuple[ProductionDay, ...]
    prediction_cutoffs: tuple[AwareDatetime, ...]
    labels_as_of: AwareDatetime
    config: DeclineTargetConfig

    @model_validator(mode="after")
    def validate_dates(self) -> "HistoricalLabelRequest":
        dates = [day.observation_date for day in self.days]
        origins = [cutoff.date() for cutoff in self.prediction_cutoffs]
        if len(dates) != len(set(dates)) or len(origins) != len(set(origins)):
            raise ValueError("duplicate observation dates or prediction origins")
        if any(cutoff > self.labels_as_of for cutoff in self.prediction_cutoffs):
            raise ValueError("prediction cutoff must not follow labels_as_of")
        return self


class DeclineLabel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    purpose: Literal["historical_supervised_target"] = "historical_supervised_target"
    origin_date: date
    prediction_cutoff: AwareDatetime
    labels_as_of: AwareDatetime
    historical_start: date
    outcome_end: date
    decline_threshold_pct: float
    status: Literal["available", "unavailable"]
    label: bool | None
    historical_mean: float | None
    future_mean: float | None
    change_pct: float | None
    milk_source: Literal["shipment", "delpro"] | None
    reason: str


def generate_decline_labels(request: HistoricalLabelRequest) -> tuple[DeclineLabel, ...]:
    """Origin t uses t-7..t-1 versus t+1..t+7, excluding t from both means.

    Cutoffs must follow the completed origin day in the agreed local timezone.
    Future actuals are consumed exclusively here as outcomes, never features.
    """
    by_date = {day.observation_date: day for day in request.days}
    results = []
    for cutoff in sorted(request.prediction_cutoffs):
        origin = cutoff.date()
        dates = comparison_dates(origin)
        window = [by_date.get(day) for day in dates]
        origin_day = window[7]
        reason = ""
        historical = future = change = None
        label = None
        milk_source = None
        if origin_day is None:
            reason = "missing_origin_day"
        elif origin_day.available_at > cutoff:
            reason = "origin_unavailable_at_prediction_cutoff"
        elif not origin_day.is_scoreable or origin_day.quality != "ok":
            reason = "ineligible_origin_quality"
        elif origin_day.target_litres_per_cow is None or origin_day.milk_source is None:
            reason = "missing_origin_production_or_source"
        elif any(day is None for day in window):
            reason = "incomplete_calendar_window"
        elif any(day.available_at > request.labels_as_of for day in window):
            reason = "actuals_not_available_as_of_label_generation"
        elif any(day.available_at > cutoff for day in window[:7]):
            reason = "historical_reference_unavailable_at_prediction_cutoff"
        elif any(not day.is_scoreable or day.quality != "ok" for day in window):
            reason = "unscoreable_or_unreliable_production"
        elif any(day.target_litres_per_cow is None for day in window):
            reason = "missing_production"
        elif any(day.milk_source is None for day in window):
            reason = "missing_milk_source"
        elif len({(day.milk_source, day.source, day.source_version) for day in window}) != 1:
            reason = "mixed_milk_sources_or_provenance"
        else:
            statistics = decline_statistics(
                [day.target_litres_per_cow for day in window[:7]],
                [day.target_litres_per_cow for day in window[8:]], request.config,
            )
            if statistics is None:
                reason = "nonpositive_historical_baseline"
            else:
                historical, future, change, label = statistics
                milk_source = window[0].milk_source
                reason = "complete_same_source_comparison"
        results.append(DeclineLabel(
            origin_date=origin, prediction_cutoff=cutoff, labels_as_of=request.labels_as_of,
            historical_start=dates[0], outcome_end=dates[-1],
            decline_threshold_pct=request.config.decline_threshold_pct,
            status="available" if label is not None else "unavailable", label=label,
            historical_mean=historical, future_mean=future, change_pct=change,
            milk_source=milk_source, reason=reason,
        ))
    return tuple(results)
