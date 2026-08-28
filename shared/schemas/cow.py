from pydantic import BaseModel

class Cow(BaseModel):
    id: str
    farm_id: str
    breed: str
    lactation_number: int = 1

