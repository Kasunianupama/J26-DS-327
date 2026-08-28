from pydantic import BaseModel
class AgronomistResponse(BaseModel): answer: str; confidence: float
