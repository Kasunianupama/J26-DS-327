from pydantic import BaseModel

class Explanation(BaseModel):
    summary: str
    factors: list[str] = []

