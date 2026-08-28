from pydantic import BaseModel
class FarmerQuery(BaseModel): query: str; farm_id: str
