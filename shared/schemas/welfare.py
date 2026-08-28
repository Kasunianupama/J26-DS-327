from pydantic import BaseModel, Field

class HerdWelfareState(BaseModel):
    farm_id: str
    welfare_score: float = Field(ge=0, le=100)
    summary: str

