from uuid import UUID
from pydantic import BaseModel, Field
from typing import Literal


class SessionCreateRequest(BaseModel):
    user_id: UUID


class HistoryRequest(BaseModel):
    user_id: UUID


class UserProfileStatusRequest(BaseModel):
    user_id: UUID


class ProviderSetupStatusRequest(BaseModel):
    user_id: UUID


class SettingsRequest(BaseModel):
    user_id: UUID


class BackendSessionRequest(BaseModel):
    user_id: UUID


class BackendSessionUpdateRequest(BaseModel):
    user_id: UUID
    username: str
    access_token: str
    refresh_token: str


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


class ProviderSetupUpdateRequest(BaseModel):
    user_id: UUID
    llm_provider: str
    llm_api_key: str = ""
    llm_base_url: str = ""
    search_provider: str
    search_api_key: str = ""
    search_base_url: str = ""


class BackupRequest(BaseModel):
    user_id: UUID
    source_path: str
    backup_path: str
    db_key: str
