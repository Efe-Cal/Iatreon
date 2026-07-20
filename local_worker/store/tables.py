from typing import Any

from sqlalchemy import Float, Integer, JSON, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass


class Profile(Base):
    __tablename__ = "profiles"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ProviderSetup(Base):
    __tablename__ = "provider_setup"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class BackendSession(Base):
    __tablename__ = "backend_session"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    username: Mapped[str] = mapped_column(String, nullable=False)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    sections: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    intake_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    doctor_session_id: Mapped[str | None] = mapped_column(String, nullable=True)


class Intake(Base):
    __tablename__ = "intakes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    chat_session_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    profile: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    transcript: Mapped[str] = mapped_column(Text, nullable=False)
    completed_at: Mapped[str] = mapped_column(String, nullable=False)


class Research(Base):
    __tablename__ = "research"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    chat_session_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    triggered_by: Mapped[str] = mapped_column(String, nullable=False)
    research_effort: Mapped[str] = mapped_column(String, nullable=False)
    research_report: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class Diagnosis(Base):
    __tablename__ = "diagnoses"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    intake_session_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    chat_session_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    report: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)

class ProfileUpdateJob(Base):
    __tablename__ = "profile_update_jobs"

    chat_session_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    dirty_at: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[float] = mapped_column(Float, nullable=False)
    claimed_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)