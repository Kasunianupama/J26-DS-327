from pydantic import BaseModel, Field

class BehavioralState(BaseModel):
    farm_id: str
    label: str
    confidence: float = Field(ge=0, le=1)

