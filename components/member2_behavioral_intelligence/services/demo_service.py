from shared.schemas.behavioral_state import BehavioralState
from shared.schemas.welfare import HerdWelfareState

def farm_behavior(farm_id: str) -> dict:
    return {"behavior": BehavioralState(farm_id=farm_id, label="routine_stable", confidence=0.78), "welfare": HerdWelfareState(farm_id=farm_id, welfare_score=82, summary="Demo welfare observation; not a clinical assessment."), "available_modalities": ["environmental", "manual_observation"]}

