"""Compatibility entry point for the Member 3 API route.

The name remains temporarily because it is an existing integration import.  The
response itself is grounded in the Member 3 synthetic data repository.
"""
from shared.schemas.predictive import PredictiveFarmContext
from shared.schemas.user import UserRole
from components.member3_farmer_reasoning.context.predictive_context import build_predictive_brief
from components.member3_farmer_reasoning.services.assistant_service import AssistantService

_assistant = AssistantService()


def answer_query(
    query: str,
    farm_id: str,
    role: UserRole,
    language: str,
    predictive_context: PredictiveFarmContext | None = None,
    conversation_id: str | None = None,
) -> dict:
    """Build a structured, grounded response from approved deterministic operations."""
    response = _assistant.answer(query, farm_id, role, language, conversation_id)
    response["demo"] = True
    response["predictive_context_used"] = False
    for recommendation in response["recommendations"]:
        recommendation["owner"] = role.value
    if predictive_context is None:
        return response
    if predictive_context.farm_id != farm_id:
        raise ValueError("predictive_context.farm_id must match farm_id")
    # Optional predictive context is an explicit interface for Member 1 output.
    # It is not presented as a real model output unless a real adapter supplies it.
    brief = build_predictive_brief(predictive_context)
    response["answer"] = f"{brief.summary} {response['answer']}"
    response["summary"] = response["answer"]
    existing = [item["action"] for item in response["recommendations"]]
    response["recommendations"] = [{"action": action, "priority": "high" if index == 0 else "medium", "owner": role.value} for index, action in enumerate(dict.fromkeys([*brief.actions, *existing]))]
    response["evidence"] = [*brief.evidence, *response["evidence"]]
    response["confidence"] = min(response["confidence"], brief.confidence)
    response["context_quality"] = 0.78 if predictive_context.confidence == "Limited" else response["context_quality"]
    response["predictive_context_used"] = True
    response["member1_integration"] = "context supplied by caller; no Member 1 service endpoint is connected"
    return response
