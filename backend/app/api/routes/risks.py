from fastapi import APIRouter
from components.member4_crisis_forecasting.services.demo_service import farm_risk, national_risk
from backend.app.api.routes.member4_research import router as research_router
from backend.app.api.routes.member4_session import router as session_router
router = APIRouter(prefix="/risks", tags=["risks"])
# Extend only the Member 4 risk router; existing demo endpoints stay independent.
router.include_router(research_router, prefix="")
router.include_router(session_router)
@router.get("/farms/{farm_id}")
def get_farm_risk(farm_id: str): return farm_risk(farm_id)
@router.get("/national")
def get_national_risk(): return national_risk()

