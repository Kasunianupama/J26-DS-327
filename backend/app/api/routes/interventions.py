from fastapi import APIRouter
from components.member1_didt.services.demo_service import simulate
from shared.schemas.intervention import InterventionScenario
router = APIRouter(prefix="/interventions", tags=["interventions"])
@router.post("/simulate")
def intervention_simulation(scenario: InterventionScenario) -> dict:
    return simulate(scenario)

