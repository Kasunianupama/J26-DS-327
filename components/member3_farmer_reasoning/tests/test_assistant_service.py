from components.member3_farmer_reasoning.services.assistant_service import AssistantService
from shared.schemas.user import UserRole


def test_herd_count_is_calculated_from_repository():
    response = AssistantService().answer("How many cows are currently on the farm?", "FARM_01", UserRole.FARM_MANAGER, "en")
    assert response["intent"] == "herd_count"
    assert "284 animals" in response["answer"]
    assert response["evidence"][0]["source"] == "animals"


def test_member2_aligned_animal_history_uses_milk_records():
    response = AssistantService().answer("What happened to animal LK-2121 in the last 30 days?", "FARM_01", UserRole.FARM_MANAGER, "en")
    assert response["intent"] == "animal_history"
    assert "LK-2121" in response["answer"]
    assert response["visualization"]["type"] == "line"


def test_ranked_follow_up_reuses_conversation_memory():
    service = AssistantService()
    first = service.answer("Which cows need attention today?", "FARM_01", UserRole.VETERINARIAN, "en")
    follow_up = service.answer("What about the second cow?", "FARM_01", UserRole.VETERINARIAN, "en", first["conversationId"])
    assert follow_up["intent"] == "animal_history"
    assert "LK-2193" in follow_up["answer"]


def test_member2_behavior_context_is_attached_to_relevant_answers():
    response = AssistantService().answer("Show my morning briefing", "FARM_01", UserRole.FARM_MANAGER, "en")

    assert response["intent"] == "morning_briefing"
    assert response["behavioralContext"]["scope"] == "herd-level"
    assert response["behavioralContext"]["routine"] == "routine stable"
    assert any(item["source"] == "member2_behavior" for item in response["evidence"])


def test_unrelated_question_is_rejected_by_domain_guard():
    response = AssistantService().answer("Write my university assignment", "FARM_01", UserRole.FARM_MANAGER, "en")
    assert response["intent"] == "domain_guard"
    assert "dairy-farm operations" in response["answer"]
