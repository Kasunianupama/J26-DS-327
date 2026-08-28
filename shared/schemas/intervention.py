from pydantic import BaseModel, Field

class InterventionScenario(BaseModel):
    farm_id: str
    intervention: str
    change_percent: float = Field(default=0, ge=-100, le=100)

class InterventionRecommendation(BaseModel):
    action: str
    rationale: str
    priority: str = "medium"

