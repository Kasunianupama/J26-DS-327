"""C1 contract adapter. Research context only; no approved warning policy exists."""
from collections import Counter
from datetime import date, datetime, timedelta
from math import isfinite
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from shared.schemas.pfoi_outlook import CONTRACT_VERSION, OutlookRow


class PublishedOutlook(OutlookRow):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    created_at: AwareDatetime


class C1ResearchContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    contract_version: Literal["1.0.0"] = "1.0.0"
    farm_id: Literal["FARM_X"] = "FARM_X"
    assessment_date: date
    assessed_at: AwareDatetime
    c1_contract_version: str = CONTRACT_VERSION
    c1_model_version: str
    c1_core_version: str | None
    c1_origin_date: date
    source_object: Literal["c1_output.outlook"] = "c1_output.outlook"
    source: Literal["model"] = "model"
    status: Literal["research_context_available", "unavailable"]
    eligible_forecast_days: int = Field(ge=0, le=7)
    mean_daily_herd_milk_forecast: float | None
    reasons: tuple[str, ...]
    research_only: Literal[True] = True
    live_warning_allowed: Literal[False] = False
    warning_status: Literal["withheld_no_approved_warning_policy"] = "withheld_no_approved_warning_policy"
    historical_availability: Literal["unknown"] = "unknown"
    recording_completeness: Literal["unknown"] = "unknown"


def assess_c1_context(rows, *, assessment_date, assessed_at, origin_date,
                      model_version, core_version):
    """Require an explicit run; never choose latest version or fill missing days.

    C1 daily horizon 1 starts on its origin, not the following day. C4 asks
    for assessment+1..+7; a same-day origin therefore uses C1 horizons 2..8.
    created_at gates snapshot presence only, never certifies historical availability.
    """
    if assessed_at.tzinfo is None or not model_version.strip():
        raise ValueError("aware_cutoff_and_explicit_version_required")
    reasons = set()
    if origin_date > assessment_date or assessment_date > assessed_at.date():
        reasons.add("invalid_origin_or_assessment_date")
    if not core_version or not core_version.strip():
        reasons.add("core_provenance_unknown")
    required = {assessment_date + timedelta(days=i) for i in range(1, 8)}
    values = {}
    seen = set()
    for raw in rows:
        r = PublishedOutlook.model_validate(raw)
        if (r.origin_date != origin_date or r.model_version != model_version
                or r.grain != "daily" or r.series != "herd_milk"):
            reasons.add("unexpected_run_or_series")
            continue
        if r.target_period not in required:
            continue
        if r.target_period in seen:
            reasons.add("duplicate_target_date")
        seen.add(r.target_period)
        failures = []
        if r.horizon != (r.target_period - origin_date).days + 1:
            failures.append("date_horizon_mismatch")
        if r.created_at > assessed_at:
            failures.append("publication_after_cutoff")
        if r.created_at.date() < origin_date:
            failures.append("publication_before_origin")
        if r.core_version != core_version:
            failures.append("mixed_core_provenance")
        if r.quality_flag != "ok":
            failures.append("quality_not_ok_or_unknown")
        if not isfinite(r.forecast) or r.forecast < 0:
            failures.append("invalid_forecast")
        if ((r.lower is None) != (r.upper is None)
                or (r.lower is not None and not (0 <= r.lower <= r.forecast <= r.upper))):
            failures.append("invalid_interval")
        reasons.update(failures)
        if not failures:
            values[r.target_period] = r.forecast
    if len(values) != 7:
        reasons.add("incomplete_seven_day_forecast")
    available = not reasons
    return C1ResearchContext(
        assessment_date=assessment_date, assessed_at=assessed_at,
        c1_origin_date=origin_date, c1_model_version=model_version,
        c1_core_version=core_version, status="research_context_available" if available else "unavailable",
        eligible_forecast_days=len(values),
        mean_daily_herd_milk_forecast=sum(values.values()) / 7 if available else None,
        reasons=tuple(sorted(reasons)) + ("availability_and_completeness_unverified", "no_approved_warning_policy"),
    )


def aggregate_summary(contexts):
    contexts = tuple(contexts)
    return dict(contract_version="1.0.0", research_only=True, live_warning_allowed=False,
                assessments=len(contexts), status_counts=dict(Counter(c.status for c in contexts)),
                reason_counts=dict(Counter(r for c in contexts for r in c.reasons)),
                validated_warnings=0, publication="disabled_no_writes")
