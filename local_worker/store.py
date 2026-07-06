import base64
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import JSON, NullPool, String, Text, create_engine, desc, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

try:
    from sqlcipher3 import dbapi2 as sqlcipher
except ImportError as exc:  # pragma: no cover - exercised only when dependency is missing
    sqlcipher = None
    _sqlcipher_import_error = exc
else:
    _sqlcipher_import_error = None


_lock = threading.RLock()
_engine: Engine | None = None
_SessionLocal: Callable[[], Session] | None = None


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


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    sections: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    intake_session_id: Mapped[str | None] = mapped_column(String, nullable=True)


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


def initialize(db_path: str, db_key: str) -> None:
    global _engine, _SessionLocal

    if sqlcipher is None:
        raise RuntimeError("sqlcipher3-binary is required for encrypted local storage") from _sqlcipher_import_error

    key = base64.b64decode(db_key, validate=True)
    if len(key) != 32:
        raise ValueError("local worker database key must be 32 bytes")

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    key_hex = key.hex()

    def connect():
        conn = sqlcipher.connect(str(path), check_same_thread=False)
        try:
            cursor = conn.cursor()
            
            try:
                cursor.execute(f"PRAGMA key = \"x'{key_hex}'\"")
                
                cursor.execute("SELECT count(*) FROM sqlite_master")
            finally:
                cursor.close()
            return conn

        except Exception:
            conn.close()
            raise

    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = create_engine("sqlite://", creator=connect, future=True, poolclass=NullPool)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
        Base.metadata.create_all(_engine)


def _reset_for_tests() -> None:
    global _engine, _SessionLocal
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None
        _SessionLocal = None


def _session() -> Session:
    if _SessionLocal is None:
        raise RuntimeError("local worker store is not initialized")
    return _SessionLocal()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_session(user_id: str) -> str:
    with _lock, _session() as db:
        session_id = str(uuid.uuid4())
        db.add(ChatSession(id=session_id, user_id=str(user_id), created_at=now(), sections=[]))
        db.commit()
        return session_id


def update_profile(profile: dict[str, Any]) -> None:
    with _lock, _session() as db:
        user_id = str(profile["user_id"])
        row = db.get(Profile, user_id)
        if row is None:
            db.add(Profile(user_id=user_id, payload=profile))
        else:
            row.payload = profile
        db.commit()


def get_profile(user_id: str) -> dict[str, Any]:
    with _lock, _session() as db:
        row = db.get(Profile, str(user_id))
        return row.payload if row else {}


def has_profile(user_id: str) -> bool:
    with _lock, _session() as db:
        return db.get(Profile, str(user_id)) is not None


def update_provider_setup(payload: dict[str, Any]) -> None:
    with _lock, _session() as db:
        user_id = str(payload["user_id"])
        row = db.get(ProviderSetup, user_id)
        if row is None:
            db.add(ProviderSetup(user_id=user_id, payload=payload))
        else:
            row.payload = payload
        db.commit()


def get_provider_setup(user_id: str) -> dict[str, Any]:
    with _lock, _session() as db:
        row = db.get(ProviderSetup, str(user_id))
        return row.payload if row else {}


def has_provider_setup(user_id: str) -> bool:
    with _lock, _session() as db:
        return db.get(ProviderSetup, str(user_id)) is not None


def profile_markdown(user_id: str) -> str:
    profile = get_profile(user_id)
    if not profile:
        return "# Patient Profile\nNo saved profile."

    lines = ["# Patient Profile"]
    demographics = profile.get("demographics") or {}
    if demographics:
        lines.extend(["", "## Demographics"])
        for key, value in demographics.items():
            lines.append(f"{key.capitalize()}: {value}")

    for title, key in [
        ("Allergies", "allergies"),
        ("Medications", "medications"),
        ("Past Medical History", "pmh"),
        ("Family History", "family_history"),
    ]:
        values = profile.get(key) or []
        if values:
            lines.extend(["", f"## {title}"])
            lines.extend(f"- {value}" for value in values)

    social = profile.get("social") or {}
    if social:
        lines.extend(["", "## Social History"])
        for key, value in social.items():
            lines.append(f"{key.capitalize()}: {value}")

    return "\n".join(lines)


def link_intake_session(chat_session_id: str | None, intake_id: str) -> None:
    if not chat_session_id:
        return
    with _lock, _session() as db:
        session = db.get(ChatSession, str(chat_session_id))
        if session is not None:
            session.intake_session_id = str(intake_id)
            db.commit()


def save_intake(user_id: str, intake_id: str, chat_session_id: str | None, profile: dict[str, Any], transcript: str) -> None:
    completed_at = now()
    with _lock, _session() as db:
        row = db.get(Intake, str(intake_id))
        payload = {
            "user_id": str(user_id),
            "chat_session_id": str(chat_session_id) if chat_session_id else None,
            "profile": profile,
            "transcript": transcript,
            "completed_at": completed_at,
        }
        if row is None:
            db.add(Intake(id=str(intake_id), **payload))
        else:
            for key, value in payload.items():
                setattr(row, key, value)

        session = db.get(ChatSession, str(chat_session_id)) if chat_session_id else None
        if session is not None:
            sections = [s for s in (session.sections or []) if s.get("id") != str(intake_id)]
            sections.append({
                "id": str(intake_id),
                "type": "intake",
                "title": profile.get("chief_complaint") or "Intake",
                "created_at": completed_at,
                "content": profile.get("medical_summary") or "_No intake summary saved._",
            })
            session.sections = sections
            session.intake_session_id = str(intake_id)
        db.commit()


def get_intake(intake_id: str) -> dict[str, Any] | None:
    with _lock, _session() as db:
        row = db.get(Intake, str(intake_id))
        if row is None:
            return None
        return {
            "id": row.id,
            "user_id": row.user_id,
            "chat_session_id": row.chat_session_id,
            "profile": row.profile,
            "transcript": row.transcript,
            "completed_at": row.completed_at,
        }


def get_intake_by_chat_session(chat_session_id: str) -> dict[str, Any] | None:
    with _lock, _session() as db:
        session = db.get(ChatSession, str(chat_session_id))
        if session is None or not session.intake_session_id:
            return None

        row = db.get(Intake, session.intake_session_id)
        if row is None:
            return None

        return {
            "id": row.id,
            "user_id": row.user_id,
            "chat_session_id": row.chat_session_id,
            "profile": row.profile,
            "transcript": row.transcript,
            "completed_at": row.completed_at,
        }


def save_research(
    user_id: str,
    research_id: str,
    chat_session_id: str | None,
    research_effort: str,
    report: str,
    citations: dict[Any, dict[str, Any]],
    triggered_by: str = "user",
) -> None:
    created_at = now()
    normalized_citations = {str(k): v for k, v in (citations or {}).items()}
    with _lock, _session() as db:
        row = db.get(Research, str(research_id))
        payload = {
            "user_id": str(user_id),
            "chat_session_id": str(chat_session_id) if chat_session_id else None,
            "triggered_by": triggered_by,
            "research_effort": research_effort,
            "research_report": report,
            "citations": normalized_citations,
            "created_at": created_at,
        }
        if row is None:
            db.add(Research(id=str(research_id), **payload))
        else:
            for key, value in payload.items():
                setattr(row, key, value)

        session = db.get(ChatSession, str(chat_session_id)) if chat_session_id else None
        if session is not None:
            sections = [s for s in (session.sections or []) if s.get("id") != str(research_id)]
            sections.append({
                "id": str(research_id),
                "type": "research",
                "title": f"Research ({research_effort})",
                "created_at": created_at,
                "content": report or "_No research report saved._",
                "citations": normalized_citations,
            })
            session.sections = sections
        db.commit()


def _research_record(row: Research) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "chat_session_id": row.chat_session_id,
        "triggered_by": row.triggered_by,
        "research_effort": row.research_effort,
        "research_report": row.research_report,
        "citations": row.citations,
        "created_at": row.created_at,
    }


def get_latest_research(user_id: str, chat_session_id: str | None, triggered_by: str = "user") -> dict[str, Any] | None:
    with _lock, _session() as db:
        stmt = (
            select(Research)
            .where(
                Research.user_id == str(user_id),
                Research.chat_session_id == (str(chat_session_id) if chat_session_id else None),
                Research.triggered_by == triggered_by,
            )
            .order_by(desc(Research.created_at))
            .limit(1)
        )
        row = db.scalars(stmt).first()
        return _research_record(row) if row else None


def save_diagnosis(user_id: str, diagnosis_id: str, intake_id: str, chat_session_id: str | None, report: dict[str, Any]) -> None:
    created_at = now()
    with _lock, _session() as db:
        row = db.get(Diagnosis, str(diagnosis_id))
        payload = {
            "user_id": str(user_id),
            "intake_session_id": str(intake_id),
            "chat_session_id": str(chat_session_id) if chat_session_id else None,
            "report": report,
            "created_at": created_at,
        }
        if row is None:
            db.add(Diagnosis(id=str(diagnosis_id), **payload))
        else:
            for key, value in payload.items():
                setattr(row, key, value)

        session = db.get(ChatSession, str(chat_session_id)) if chat_session_id else None
        if session is not None:
            sections = [s for s in (session.sections or []) if s.get("id") != str(diagnosis_id)]
            sections.append({
                "id": str(diagnosis_id),
                "type": "diagnosis",
                "title": "Diagnosis",
                "created_at": created_at,
                "content": report,
            })
            session.sections = sections
        db.commit()


def get_citation_text(research_id: str, citation_num: int) -> str:
    with _lock, _session() as db:
        research = db.get(Research, str(research_id))
        citations = research.citations if research else {}
    citation = (citations or {}).get(str(citation_num)) or {}
    return citation.get("text") or citation.get("full_text") or ""


def list_history(user_id: str) -> list[dict[str, Any]]:
    with _lock, _session() as db:
        stmt = (
            select(ChatSession)
            .where(ChatSession.user_id == str(user_id))
            .order_by(desc(ChatSession.created_at))
        )
        sessions = db.scalars(stmt).all()
        return [
            {
                "id": session.id,
                "created_at": session.created_at,
                "sections": session.sections or [],
            }
            for session in sessions
        ]
