from uuid import UUID
from pydantic import BaseModel, Field
from typing import Literal


class SessionCreateRequest(BaseModel):
    user_id: UUID


class HistoryRequest(BaseModel):
    user_id: UUID


class UserProfileStatusRequest(BaseModel):
    user_id: UUID


class DiagnosisRequest(BaseModel):
    user_id: UUID
    intake_id: UUID
    session_id: UUID | None = None
    

class ChatRequest(BaseModel):
    user_id: UUID
    message: str
    conversation_id: UUID | None
    session_id: UUID | None


class ResearchRequest(BaseModel):
    user_id: UUID
    intake_id: UUID
    session_id: UUID | None = None
    research_effort: Literal["fast", "standard", "deep", "web"] = "standard"


class CitationTextRequest(BaseModel):
    user_id: UUID
    research_session_id: UUID
    citation_num: int


class WorkerInitRequest(BaseModel):
    db_path: str
    db_key: str


class UserProfileUpdateRequest(BaseModel):
    user_id: UUID
    demographics: dict[str, str] = Field(default_factory=dict)
    pmh: list[str] = Field(default_factory=list)
    medications: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    family_history: list[str] = Field(default_factory=list)
    social: dict[str, str] = Field(default_factory=dict)
    medical_summary: str | None = None
