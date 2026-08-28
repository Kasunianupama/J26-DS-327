from fastapi import APIRouter
from pydantic import BaseModel
from components.member3_farmer_reasoning.services.demo_service import answer_query
from shared.schemas.user import UserRole
router = APIRouter(prefix="/agent", tags=["digital-agronomist"])
class AgentQuery(BaseModel):
    query: str
    farm_id: str
    role: UserRole = UserRole.FARM_MANAGER
    language: str = "en"
@router.post("/query")
def query_agent(request: AgentQuery) -> dict:
    return answer_query(request.query, request.farm_id, request.role, request.language)

