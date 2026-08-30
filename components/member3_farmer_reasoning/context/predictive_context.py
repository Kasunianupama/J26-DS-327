"""Translate predictive outputs into safe, role-neutral decision context."""

from dataclasses import dataclass

from shared.schemas.predictive import PredictiveFarmContext


@dataclass(frozen=True)
class PredictiveBrief:
    summary: str
    actions: list[str]
    evidence: list[dict[str, str]]
    confidence: float
    requires_verification: bool


def build_predictive_brief(context: PredictiveFarmContext) -> PredictiveBrief:
    milk = context.milk_litres_per_day
    drivers = context.drivers
    uncertainty = milk.upper - milk.lower
    change = drivers.calvings - drivers.dry_offs
    direction = "fall" if change < 0 else "increase" if change > 0 else "remain broadly stable"

    summary = (
        f"For the next {context.forecast_window_days} days, milk is expected to average "
        f"{milk.expected:,.0f} L/day (likely range {milk.lower:,.0f}–{milk.upper:,.0f} L/day). "
        f"Milking capacity may {direction}: {drivers.dry_offs} dry-offs and {drivers.calvings} calvings are in the forecast window."
    )
    actions: list[str] = []
    verification = context.confidence == "Limited" or drivers.transition_share >= 0.30
    if verification:
        actions.append(
            "Verify pregnancy, calving, and dry-off records before changing production, processing, or sales plans."
        )
    if drivers.thi is not None and drivers.thi >= 72:
        actions.append(
            "Check cooling, shade, and unrestricted water access during the hottest shift; record affected-cow observations."
        )
    if change < 0:
        actions.append(
            "Review dry-cow, calving-pen, and product-volume plans for the expected reduction in milking capacity."
        )
    for animal in context.priority_animals[:3]:
        actions.append(f"Follow up {animal.animal_id}: {animal.reason}")
    if not actions:
        actions.append("Continue planned herd checks and compare the next recorded milk result with the forecast range.")

    evidence = [
        {
            "title": "Milk forecast",
            "source_type": "prediction",
            "reference": f"{milk.expected:,.0f} L/day; range width {uncertainty:,.0f} L/day; confidence {context.confidence}",
        },
        {
            "title": "Herd-transition drivers",
            "source_type": "forecast driver",
            "reference": f"{drivers.dry_offs} dry-offs, {drivers.calvings} calvings, transition-dependent milk {drivers.transition_share:.0%}",
        },
    ]
    evidence.extend(
        {"title": finding.title, "source_type": "predictive finding", "reference": finding.summary}
        for finding in context.findings[:3]
    )
    confidence = {"High": 0.88, "Moderate": 0.74, "Limited": 0.55}[context.confidence]
    return PredictiveBrief(summary, actions, evidence, confidence, verification)
