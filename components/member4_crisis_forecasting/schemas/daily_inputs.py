"""Proposed daily aggregate boundary; not a mapping of database columns."""

from datetime import date
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class DailyRiskInput(BaseModel):
    """One Farm X day, using only information available at the assessment cutoff.

    Counts are recorded daily totals; None means unknown, never a recorded zero.
    Episode meanings and denominators require producer agreement before real use.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    farm_name: Literal["Farm X"] = "Farm X"
    observation_date: date
    observation_end: AwareDatetime
    available_at: AwareDatetime
    source_version: str = Field(min_length=1)
    source: Literal["synthetic", "published"]
    quality: Literal["ok", "partial", "unavailable"]
    thi_mean: float | None = None  # Dimensionless; formula owned by producer.
    n_sessions: int | None = Field(default=None, ge=0, strict=True)
    n_blood_alarms: int | None = Field(default=None, ge=0, strict=True)
    n_conductivity_alarms: int | None = Field(default=None, ge=0, strict=True)
    mastitis_episodes: int | None = Field(default=None, ge=0, strict=True)
    udder_teat_episodes: int | None = Field(default=None, ge=0, strict=True)
    other_health_episodes: int | None = Field(default=None, ge=0, strict=True)

    @model_validator(mode="after")
    def check_metadata(self) -> "DailyRiskInput":
        if not self.source_version.strip():
            raise ValueError("source_version must not be blank")
        if self.observation_end.date() != self.observation_date:
            raise ValueError("observation_end must fall on the observation date")
        if self.available_at < self.observation_end:
            raise ValueError("available_at must not precede observation_end")
        return self


class DailyInputBatch(BaseModel):
    """A cutoff and daily records; all timestamps must carry timezone offsets."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    assessment_cutoff: AwareDatetime
    days: tuple[DailyRiskInput, ...]

    @model_validator(mode="after")
    def check_days(self) -> "DailyInputBatch":
        dates = [day.observation_date for day in self.days]
        if len(dates) != len(set(dates)):
            raise ValueError("duplicate observation dates")
        for day in self.days:
            if day.available_at > self.assessment_cutoff:
                raise ValueError("daily input was unavailable at assessment cutoff")
        return self


def rate_per_session(count: int | None, sessions: int | None) -> float | None:
    """Events per session, not a probability; multiple events may occur per session."""
    for value in (count, sessions):
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError("counts must be nonnegative integers or None")
    if count is None or sessions is None or sessions == 0:
        return None
    return count / sessions
