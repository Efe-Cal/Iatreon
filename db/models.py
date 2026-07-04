from sqlalchemy import String, Text, Integer, Float, Boolean, ForeignKey, DateTime, Uuid
from sqlalchemy.dialects.postgresql import JSONB as JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
from typing import Optional
import uuid
from .db import Base

class User(Base):
    __tablename__ = "users"
    email: Mapped[Optional[str]] = mapped_column(String, unique=True, default=None)
    password_hash: Mapped[Optional[str]] = mapped_column(Text, default=None)
    session_key_salt: Mapped[Optional[str]] = mapped_column(String, default=None)
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default_factory=uuid.uuid4)
    ssh_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True, unique=True, default=None)
    encrypted_data_key: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default_factory=datetime.utcnow)

class AuthSession(Base):
    __tablename__ = "auth_sessions"
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))
    refresh_token_hash: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default_factory=uuid.uuid4)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default_factory=datetime.utcnow)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default_factory=datetime.utcnow)

class UserProfile(Base):
    __tablename__ = "user_profile"
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    encrypted_payload: Mapped[Optional[str]] = mapped_column(Text, default=None)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default_factory=datetime.utcnow, onupdate=datetime.utcnow)

class ChatSession(Base):
    __tablename__ = "chat_sessions"
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default_factory=uuid.uuid4)
    intake_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("intake_sessions.id"), default=None
    )
    intake_session: Mapped[Optional["IntakeSession"]] = relationship(foreign_keys=[intake_session_id], default=None)
    research_sessions: Mapped[list["ResearchSession"]] = relationship(back_populates="chat_session", default_factory=list)
    doctor_session: Mapped[Optional["DoctorSession"]] = relationship(
        "DoctorSession", back_populates="chat_session", foreign_keys="[DoctorSession.chat_session_id]",
        primaryjoin="ChatSession.id == DoctorSession.chat_session_id", default=None, uselist=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default_factory=datetime.utcnow)

class IntakeSession(Base):
    __tablename__ = "intake_sessions"
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default_factory=uuid.uuid4)
    encrypted_payload: Mapped[Optional[str]] = mapped_column(Text, default=None)
    status: Mapped[str] = mapped_column(String, default="in_progress")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default_factory=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)

class ResearchSession(Base):
    __tablename__ = "research_sessions"
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default_factory=uuid.uuid4)
    encrypted_payload: Mapped[Optional[str]] = mapped_column(Text, default=None)
    chat_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("chat_sessions.id"), default=None)
    chat_session: Mapped[Optional["ChatSession"]] = relationship(back_populates="research_sessions", default=None)
    triggered_by: Mapped[str] = mapped_column(String, default="user")
    research_effort: Mapped[str] = mapped_column(String, default="standard")
    next_citation_num: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default_factory=datetime.utcnow)

class DiagnosisSession(Base):
    __tablename__ = "diagnosis_sessions"
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))
    intake_session_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("intake_sessions.id"))
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default_factory=uuid.uuid4)
    encrypted_payload: Mapped[Optional[str]] = mapped_column(Text, default=None)
    chat_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("chat_sessions.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default_factory=datetime.utcnow)

class DoctorSession(Base):
    __tablename__ = "doctor_sessions"
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default_factory=uuid.uuid4)
    chat_session_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("chat_sessions.id"), default=None)
    thread_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), default=None)
    chat_session: Mapped[Optional["ChatSession"]] = relationship(back_populates="doctor_session", foreign_keys=[chat_session_id], default=None)

class WebSearchResult(Base):
    __tablename__ = "web_search_results"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default_factory=uuid.uuid4)
    query: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String, default="")
    title: Mapped[Optional[str]] = mapped_column(String, default="")
    highlights: Mapped[Optional[str]] = mapped_column(Text, default="")
    full_content: Mapped[Optional[str]] = mapped_column(Text, default="")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default_factory=datetime.utcnow)

class Article(Base):
    __tablename__ = "articles"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default_factory=uuid.uuid4)
    pubmed_id: Mapped[Optional[str]] = mapped_column(String, unique=True, default=None)
    pmc_id: Mapped[Optional[str]] = mapped_column(String, unique=True, default=None)
    doi: Mapped[Optional[str]] = mapped_column(String, unique=True, default=None)
    openalex_id: Mapped[Optional[str]] = mapped_column(String, unique=True, default=None)
    title: Mapped[str] = mapped_column(Text, default="")
    abstract: Mapped[Optional[str]] = mapped_column(Text, default="")
    full_text: Mapped[Optional[str]] = mapped_column(Text, default="")
    pdf_url: Mapped[Optional[str]] = mapped_column(String, default="")
    authors: Mapped[Optional[list]] = mapped_column(JSON, default_factory=list)
    journal: Mapped[Optional[str]] = mapped_column(String, default="")
    year: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    study_type: Mapped[Optional[str]] = mapped_column(String, default="")
    keywords: Mapped[Optional[list]] = mapped_column(JSON, default_factory=list)
    mesh_terms: Mapped[Optional[list]] = mapped_column(JSON, default_factory=list)
    citation_count: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    quality_score: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    full_text_available: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[Optional[str]] = mapped_column(String, default="")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default_factory=datetime.utcnow)

class BookSection(Base):
    __tablename__ = "book_sections"
    accession_id: Mapped[str] = mapped_column(String, unique=True)
    title: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String)
    text: Mapped[Optional[str]] = mapped_column(Text)
    url: Mapped[Optional[str]] = mapped_column(String)
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default_factory=uuid.uuid4)
    full_text_available: Mapped[bool] = mapped_column(Boolean, default=False)

