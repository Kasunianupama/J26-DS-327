from fastapi import APIRouter
from pydantic import BaseModel
from components.member3_farmer_reasoning.services.demo_service import answer_query
from shared.schemas.user import UserRole
from shared.schemas.predictive import PredictiveFarmContext
router = APIRouter(prefix="/agent", tags=["digital-agronomist"])
class AgentQuery(BaseModel):
    query: str
    farm_id: str
    role: UserRole = UserRole.FARM_MANAGER
    language: str = "en"
    predictive_context: PredictiveFarmContext | None = None
    conversation_id: str | None = None
@router.post("/query")
def query_agent(request: AgentQuery) -> dict:
    return answer_query(request.query, request.farm_id, request.role, request.language, request.predictive_context, request.conversation_id)
