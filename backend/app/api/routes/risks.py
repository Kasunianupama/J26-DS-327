from fastapi import APIRouter
from components.member4_crisis_forecasting.services.demo_service import farm_risk, national_risk
router = APIRouter(prefix="/risks", tags=["risks"])
@router.get("/farms/{farm_id}")
def get_farm_risk(farm_id: str): return farm_risk(farm_id)
@router.get("/national")
def get_national_risk(): return national_risk()

