from uuid import UUID
from pydantic import BaseModel
from typing import Literal

class DiagnosisRequest(BaseModel):
    intake_id: UUID
    session_id: UUID | None = None
    
class ChatRequest(BaseModel):
    message: str
    conversation_id: UUID | None
    session_id: UUID | None

class ResearchRequest(BaseModel):
    intake_id: UUID
    session_id: UUID | None = None
    research_effort: Literal["fast", "standard", "deep", "web"] = "standard"


class CitationTextRequest(BaseModel):
    research_session_id: UUID
    citation_num: int