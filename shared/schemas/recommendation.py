from pydantic import BaseModel

class Recommendation(BaseModel):
    action: str
    priority: str = "medium"
    owner: str | None = None
