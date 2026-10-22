"""Historical THI references fitted exclusively on an explicit training window."""

from datetime import date
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from components.member4_crisis_forecasting.schemas.daily_inputs import DailyInputBatch


class BaselineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    training_start: date
    training_end: date
    percentile: float = Field(gt=0, lt=100, allow_inf_nan=False)
    minimum_days: int = Field(ge=2, strict=True)


class ThiBaseline(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    config: BaselineConfig
    status: Literal["ready", "insufficient_data"]
    usable_days: int
    excluded_days: int
    threshold: float | None
    source_version: str | None
    source: Literal["synthetic", "published"] | None
    fitted_as_of: AwareDatetime


def fit_thi_baseline(batch: DailyInputBatch, config: BaselineConfig) -> ThiBaseline:
    """Linear-interpolated percentile of quality-ok daily means.

    No seasonal adjustment is implied. Out-of-window rows are excluded, never
    used to fill a short training window. Availability is checked by the batch.
    """
    if config.training_start > config.training_end:
        raise ValueError("training_start must not follow training_end")
    eligible = [day for day in batch.days
                if config.training_start <= day.observation_date <= config.training_end
                and day.quality == "ok" and day.thi_mean is not None]
    provenance = {(day.source, day.source_version) for day in eligible}
    if len(provenance) > 1:
        raise ValueError("baseline requires one source and source_version")
    values = sorted(day.thi_mean for day in eligible)
    threshold = None
    if len(values) >= config.minimum_days:
        position = (len(values) - 1) * config.percentile / 100
        lower = int(position)
        upper = min(lower + 1, len(values) - 1)
        threshold = values[lower] + (values[upper] - values[lower]) * (position - lower)
    source, version = next(iter(provenance), (None, None))
    return ThiBaseline(
        config=config, status="ready" if threshold is not None else "insufficient_data",
        usable_days=len(values), excluded_days=len(batch.days) - len(values),
        threshold=threshold, source=source, source_version=version,
        fitted_as_of=batch.assessment_cutoff,
    )

