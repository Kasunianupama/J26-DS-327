from pydantic import BaseModel

class EvidenceSource(BaseModel):
    title: str
    source_type: str
    reference: str | None = None

