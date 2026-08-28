from pydantic import BaseModel, Field

class DairyRiskScore(BaseModel):
    farm_id: str
    score: float = Field(ge=0, le=100)
    level: str
    drivers: list[str] = []

class NationalDairyRiskIndex(BaseModel):
    score: float = Field(ge=0, le=100)
    level: str
    farms_considered: int = Field(ge=0)

