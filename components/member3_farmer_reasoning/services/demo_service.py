from shared.schemas.user import UserRole

def answer_query(query: str, farm_id: str, role: UserRole, language: str) -> dict:
    return {"answer": f"Demo integration response for {farm_id}: review recent feed, heat, and routine observations before making changes.", "confidence": 0.87, "context_quality": 0.91, "intent": "diagnostic", "evidence": [], "recommendations": [{"action": "Check water access and feeding consistency during the next shift.", "priority": "medium", "owner": role.value}], "visualizations": [], "economic_context": None, "abstained": False, "language": language, "demo": True}

