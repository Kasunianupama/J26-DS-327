from fastapi import APIRouter
from components.member2_behavioral_intelligence.services.demo_service import farm_behavior
router = APIRouter(prefix="/behavior", tags=["behavior"])
@router.get("/{farm_id}")
def behavior(farm_id: str) -> dict:
    return farm_behavior(farm_id)

