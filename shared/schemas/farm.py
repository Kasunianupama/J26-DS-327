from pydantic import BaseModel, Field

class Farm(BaseModel):
    id: str
    name: str
    district: str = "Demo District"
    herd_size: int = Field(ge=0)

