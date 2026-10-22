"""Snapshot targets only: no fabricated metadata or point-in-time assurances."""

from dataclasses import dataclass
from datetime import date
from collections.abc import Sequence

from components.member4_crisis_forecasting.schemas.historical_dataset import ApprovedAggregate
from components.member4_crisis_forecasting.prediction.decline_target import (
    DeclineTargetConfig, comparison_dates, decline_statistics,
)


@dataclass(frozen=True)
class RetrospectiveTarget:
    origin: date
    outcome_end: date
    label: bool | None
    reason: str


def retrospective_targets(
    rows: Sequence[ApprovedAggregate], milk_source: str, config: DeclineTargetConfig,
) -> tuple[RetrospectiveTarget, ...]:
    """Use ETL snapshot eligibility as a target selection rule, not feature quality.

    Same 15 dates and arithmetic as the historical generator, but availability
    and recording completeness are UNKNOWN. Never feed these to a live API.
    """
    if milk_source not in {"shipment", "delpro"}:
        raise ValueError("invalid_milk_source")
    by_date = {row.date: row for row in rows}
    if len(by_date) != len(rows):
        raise ValueError("duplicate_dates")
    targets = []
    for row in sorted(rows, key=lambda item: item.date):
        if row.target_source != milk_source:
            continue
        dates = comparison_dates(row.date)
        window = [by_date.get(day) for day in dates]
        label = None
        if any(day is None for day in window):
            reason = "incomplete_calendar_window"
        elif any(day.target_source != milk_source for day in window):
            reason = "mixed_or_missing_milk_source"
        elif any(not day.is_scoreable for day in window):
            reason = "etl_ineligible_window"
        elif any(day.target_litres_per_cow is None for day in window):
            reason = "missing_production"
        else:
            statistics = decline_statistics(
                [day.target_litres_per_cow for day in window[:7]],
                [day.target_litres_per_cow for day in window[8:]], config,
            )
            reason = "nonpositive_historical_baseline" if statistics is None else "retrospective_snapshot_target"
            if statistics is not None:
                label = statistics[-1]
        targets.append(RetrospectiveTarget(row.date, dates[-1], label, reason))
    return tuple(targets)
