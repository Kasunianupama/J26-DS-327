"""Rank completed model-based what-if estimates without asserting causality."""
import math

from components.member1_didt.schemas.counterfactual import (
    CombinedScenarioEstimate, RankedAlternative, ScenarioEstimate, ScenarioRecommendation,
)


def _ranked_candidate(estimate, alternative_type: str) -> RankedAlternative | None:
    predicted = estimate.counterfactual_predicted_milk_yield_l_day
    baseline = estimate.baseline_predicted_milk_yield_l_day
    absolute_change = estimate.absolute_yield_change_l_day
    if (
        estimate.scenario_status != "ESTIMATED_MODEL_INPUT_PERTURBATION"
        or predicted is None or baseline is None or absolute_change is None
        or not all(math.isfinite(value) for value in (predicted, baseline, absolute_change))
    ):
        return None

    support_status = estimate.model_support_status
    if support_status != "PASSED":
        return None
    return RankedAlternative(
        rank=0,
        scenario_id=estimate.scenario_id,
        alternative_type=alternative_type,
        name=estimate.name,
        scenario_status=estimate.scenario_status,
        predicted_milk_yield_l_day=predicted,
        baseline_predicted_milk_yield_l_day=baseline,
        absolute_yield_change_l_day=absolute_change,
        percentage_yield_change=estimate.percentage_yield_change,
        model_version=estimate.model_version,
        model_support_status=support_status,
        operational_feasibility_validated=False,
    )


def rank_and_recommend(
    scenarios: list[ScenarioEstimate],
    combined_scenario: CombinedScenarioEstimate | None,
) -> tuple[list[RankedAlternative], ScenarioRecommendation | None, str]:
    """Sort eligible predictions by next-day yield, descending, with stable ties."""
    candidates = [candidate for item in scenarios if (candidate := _ranked_candidate(item, "individual"))]
    if combined_scenario is not None:
        candidate = _ranked_candidate(combined_scenario, "combined")
        if candidate is not None:
            candidates.append(candidate)

    candidates.sort(key=lambda item: item.predicted_milk_yield_l_day, reverse=True)
    ranked = [item.model_copy(update={"rank": index}) for index, item in enumerate(candidates, start=1)]
    if not ranked:
        all_estimates = list(scenarios) + ([combined_scenario] if combined_scenario is not None else [])
        if all_estimates and all(
            item.model_support_status in {"OUTSIDE_TRAINING_SUPPORT", "RANGE_UNAVAILABLE"}
            for item in all_estimates
        ):
            reason = "No alternative passed the model's observed training-support checks; no recommendation was produced."
        else:
            reason = "No alternative has a valid available counterfactual prediction; no recommendation was produced."
        return ranked, None, reason

    best = ranked[0]
    recommendation = ScenarioRecommendation(
        **best.model_dump(),
        explanation=(
            "This alternative has the highest predicted next-day milk yield among the evaluated alternatives. "
            "It is a model-based ranking, not a causal optimum or a guaranteed real-world improvement."
        ),
        limitations=[
            "Farm operational feasibility has not been validated.",
            "The model estimates an observational prediction difference, not a verified intervention effect.",
        ],
    )
    return ranked, recommendation, recommendation.explanation

