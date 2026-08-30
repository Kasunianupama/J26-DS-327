"""Deterministic, role-aware demo responses for the Component 3 integration UI."""
from shared.schemas.user import UserRole


def _intent_for(query: str) -> str:
    normalized = query.lower()
    if any(word in normalized for word in ("trend", "july", "monthly", "month")): return "trend"
    if any(word in normalized for word in ("health", "sick", "disease", "cow", "lameness")): return "health"
    if any(word in normalized for word in ("heat", "hot", "water", "temperature", "thi", "usna")): return "heat"
    if any(word in normalized for word in ("risk", "alert", "crisis", "ndri", "escalat")): return "risk"
    return "production"


RESPONSES: dict[str, dict[UserRole, tuple[str, list[str]]]] = {
    "trend": {
        UserRole.FARM_WORKER: ("The July production trend has reduced toward the end of the month. Continue the daily routine checks and report abnormal cow behaviour.", ["Complete water and cooling checks.", "Follow the planned feeding routine.", "Report abnormal observations."]),
        UserRole.VETERINARIAN: ("The July production trend should be interpreted with health, welfare, and heat-related observations before attributing a cause.", ["Review health and welfare observations.", "Assess heat-related signs.", "Record clinical findings for follow-up."]),
        UserRole.FARM_MANAGER: ("The July trend shows observed production moving below the expected range in the second half of the month. Review cooling, water access, and feed timing before selecting a management response.", ["Review the July trend and daily farm notes.", "Verify cooling, water, and feeding controls.", "Assign follow-up and review the next reporting period."]),
        UserRole.NLDB_MANAGEMENT: ("The July trend indicates a farm-level production decline requiring management follow-up. Monitor whether the pattern persists and confirm the farm response.", ["Confirm farm-level follow-up ownership.", "Monitor the next reporting period.", "Review recurring patterns in the strategic brief."]),
    },
    "health": {
        UserRole.FARM_WORKER: ("Cow health needs an on-site observation. Check appetite, movement, water intake, and visible abnormal signs, then report concerns to the supervisor.", ["Observe cow 312 and record abnormal signs.", "Confirm water access and feed intake.", "Notify the supervisor or veterinarian if concerns continue."]),
        UserRole.VETERINARIAN: ("The available context indicates that cow health should be reviewed clinically. Use the current observation with history and welfare signs before deciding on treatment.", ["Perform a focused clinical examination.", "Review recent health and activity observations.", "Document findings and treatment decisions."]),
        UserRole.FARM_MANAGER: ("A cow-health concern requires prompt verification and clear ownership. Arrange a welfare check and confirm whether veterinary review is needed.", ["Assign an on-site welfare check.", "Confirm feed, water, and housing conditions.", "Escalate persistent findings to the veterinarian."]),
        UserRole.NLDB_MANAGEMENT: ("This is a farm-level animal-welfare matter. Monitor that the farm has assigned follow-up and escalate only if it becomes a repeated material risk pattern.", ["Confirm farm-level follow-up ownership.", "Monitor unresolved welfare incidents.", "Review recurring patterns in the management summary."]),
    },
    "heat": {
        UserRole.FARM_WORKER: ("Warm conditions may affect cow comfort. Check fans, shade, and water points during the afternoon shift and report heavy breathing or reduced activity.", ["Check fans and shade.", "Make sure water points are accessible.", "Report abnormal breathing or behaviour."]),
        UserRole.VETERINARIAN: ("Heat-related welfare signs should be assessed alongside respiration, activity, hydration, and current health history before a clinical decision.", ["Assess respiration and hydration.", "Review affected animals and welfare observations.", "Advise on welfare safeguards if signs persist."]),
        UserRole.FARM_MANAGER: ("Heat conditions may affect comfort and production. Verify cooling capacity, water access, and the afternoon routine before changing plans.", ["Verify cooling and water availability.", "Confirm staff checks during the hottest period.", "Review the herd response before the next decision."]),
        UserRole.NLDB_MANAGEMENT: ("This is an environmental-operational risk requiring farm follow-up. Review whether farm controls and escalation procedures are active.", ["Confirm local heat-response procedures.", "Monitor farms with unresolved heat alerts.", "Review resource needs in the management brief."]),
    },
    "risk": {
        UserRole.FARM_WORKER: ("Follow the current farm instructions and report any abnormal animal, equipment, water, or feed condition immediately.", ["Complete shift checks.", "Report abnormal conditions promptly.", "Follow supervisor instructions."]),
        UserRole.VETERINARIAN: ("Review the welfare and health implications of the reported risk. Prioritise animals with abnormal observations and advise on clinical escalation.", ["Review priority animals.", "Confirm welfare safeguards.", "Record clinical escalation advice."]),
        UserRole.FARM_MANAGER: ("The reported risk should be verified against current farm conditions before action. Assign an owner, confirm controls, and track the outcome.", ["Verify the condition on site.", "Assign action ownership and timing.", "Review the outcome at the next farm check."]),
        UserRole.NLDB_MANAGEMENT: ("Use this risk signal for oversight and escalation planning. It guides review priorities but does not replace a farm-level assessment.", ["Confirm farm follow-up status.", "Review unresolved risk patterns.", "Escalate material issues through management."]),
    },
    "production": {
        UserRole.FARM_WORKER: ("Today’s production situation needs simple shift checks. Confirm water, cooling, and the feeding routine, then report abnormal cow behaviour.", ["Check water and cooling.", "Confirm the feeding routine.", "Report abnormal observations."]),
        UserRole.VETERINARIAN: ("The production change should be interpreted with current health, welfare, and heat-related observations before attributing a cause.", ["Review health and welfare observations.", "Assess heat-related signs.", "Record clinical findings for follow-up."]),
        UserRole.FARM_MANAGER: ("Today’s production outlook needs attention. Verify cooling, water access, and the afternoon feeding routine before changing plans.", ["Check cooling and water access.", "Confirm feeding timing against the planned routine.", "Review the herd response tomorrow."]),
        UserRole.NLDB_MANAGEMENT: ("Use the production signal to prioritise management review. Confirm the farm response and monitor persistence before broader escalation.", ["Confirm local management follow-up.", "Monitor the next reporting period.", "Review recurring issues in the strategic brief."]),
    },
}


def answer_query(query: str, farm_id: str, role: UserRole, language: str) -> dict:
    intent = _intent_for(query)
    answer, actions = RESPONSES[intent][role]
    if language == "si-Latn": answer = "Me prashnayata sambandha karunu pariksha karala, sisilaneeya, jala praveshaya saha ranchu nirikshanaya mulinma balanna. " + answer
    elif language == "si": answer = "මෙම ප්‍රශ්නය සඳහා අවශ්‍ය කරුණු පරීක්ෂා කර, සිසිලනය, ජල ප්‍රවේශය සහ රංචු නිරීක්ෂණය පළමුව සමාලෝචනය කරන්න."
    elif language == "ta": answer = "இந்தக் கேள்விக்கான தகவலைச் சரிபார்த்து, குளிர்வித்தல், தண்ணீர் அணுகல் மற்றும் மந்தை கண்காணிப்பை முதலில் மதிப்பாய்வு செய்யவும்."
    return {"answer": answer, "confidence": 0.87, "context_quality": 0.91, "intent": intent, "evidence": [], "recommendations": [{"action": action, "priority": "medium", "owner": role.value} for action in actions], "visualizations": [], "economic_context": None, "abstained": False, "language": language, "demo": True}
