from pydantic import BaseModel, Field

class MilkYieldPrediction(BaseModel):
    farm_id: str
    predicted_litres: float = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    model_version: str = "demo"

