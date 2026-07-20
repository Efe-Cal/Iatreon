import base64
import hashlib
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import Float, Integer, JSON, NullPool, String, Text, create_engine, desc, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from local_worker.provider_config import backend_api_url

try:
    from sqlcipher3 import dbapi2 as sqlcipher
except ImportError as exc:  # pragma: no cover - exercised only when dependency is missing
    sqlcipher = None
    _sqlcipher_import_error = exc
else:
    _sqlcipher_import_error = None
    
import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


_lock = threading.RLock()
_engine: Engine | None = None
_SessionLocal: Callable[[], Session] | None = None

_connection_factory = None
_checkpoint_connection = None
_checkpointer = None
PROFILE_JOB_LEASE_SECONDS = 15 * 60

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


def initialize(db_path: str, db_key: str) -> None:
    global _engine, _SessionLocal, _connection_factory

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
                cursor.execute("PRAGMA busy_timeout = 5000")
                cursor.execute("SELECT count(*) FROM sqlite_master")
            finally:
                cursor.close()
            return conn

        except Exception:
            conn.close()
            raise

    _connection_factory = connect


    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = create_engine("sqlite://", creator=connect, future=True, poolclass=NullPool)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
        Base.metadata.create_all(_engine)


def calculate_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


async def create_encrypted_backup(source_path: Path, backup_path: Path, db_key: str) -> str:
    if not source_path.exists():
        raise FileNotFoundError(f"Source database file does not exist: {source_path}")

    backup_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path.unlink(missing_ok=True)

    source_connection = sqlcipher.connect(str(source_path), check_same_thread=False)
    backup_connection = sqlcipher.connect(str(backup_path), check_same_thread=False)

    key = base64.b64decode(db_key, validate=True)
    key_hex = key.hex()

    try:
        source_connection.execute(f"PRAGMA key = \"x'{key_hex}'\"")
        backup_connection.execute(f"PRAGMA key = \"x'{key_hex}'\"")

        source_connection.execute("SELECT count(*) FROM sqlite_master")

        source_connection.backup(backup_connection)
        backup_connection.commit()

        result = backup_connection.execute("PRAGMA cipher_integrity_check").fetchall()

        if result:
            raise RuntimeError(f"Backup integrity check failed: {result}")

    except Exception:
        backup_connection.close()
        source_connection.close()
        backup_path.unlink(missing_ok=True)
        raise
    else:
        backup_connection.close()
        source_connection.close()

    if not backup_path.is_file() or backup_path.stat().st_size == 0:
        backup_path.unlink(missing_ok=True)
        raise RuntimeError("Backup file was not created correctly")

    return calculate_sha256(backup_path)


async def upload_backup(backup_path: Path, user_id: str, checksum: str) -> None:
    import httpx

    if not backup_path.is_file() or backup_path.stat().st_size == 0:
        raise FileNotFoundError(f"Backup file does not exist or is empty: {backup_path}")

    api_url = backend_api_url() + "/backup/upload"
    access_token = get_backend_session(user_id).get("access_token")
    if not access_token:
        raise RuntimeError("No access token found for user, cannot upload backup")

    headers = {"Authorization": f"Bearer {access_token}"}

    async with httpx.AsyncClient() as client:
        response = await client.post(api_url, headers=headers, timeout=30)
        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to request backup upload: {response.status_code} {response.text}"
            )
        upload_url_request = response.json()
        upload_url = upload_url_request["upload_url"]
        backup_id = upload_url_request["backup_id"]

        with backup_path.open("rb") as file:
            response = await client.put(
                upload_url,
                data=file,
                headers={"Content-Type": "application/octet-stream"},
                timeout=300,
            )
            if response.status_code != 200:
                raise RuntimeError(f"Failed to upload backup: {response.status_code} {response.text}")

        response = await client.post(
            api_url + f"/{backup_id}/complete",
            json={"checksum": checksum},
            headers=headers,
            timeout=30,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to complete backup upload: {response.status_code} {response.text}"
            )


async def download_backup(backup_id: str, user_id: str, destination_path: Path) -> None:
    import httpx

    api_url = backend_api_url() + f"/backup/download/{backup_id}"
    access_token = get_backend_session(user_id).get("access_token")
    if not access_token:
        raise RuntimeError("No access token found for user, cannot download backup")

    headers = {"Authorization": f"Bearer {access_token}"}

    async with httpx.AsyncClient() as client:
        response = await client.get(api_url, headers=headers, timeout=30)
        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to request backup download: {response.status_code} {response.text}"
            )
        download_url_request = response.json()
        download_url = download_url_request["download_url"]

        response = await client.get(download_url, timeout=300)
        if response.status_code != 200:
            raise RuntimeError(f"Failed to download backup: {response.status_code} {response.text}")

        destination_path.parent.mkdir(parents=True, exist_ok=True)
        with destination_path.open("wb") as file:
            file.write(response.content)

    checksum = calculate_sha256(destination_path)
    if checksum != download_url_request["checksum"]:
        raise RuntimeError(
            "Downloaded backup checksum does not match: "
            f"{checksum} != {download_url_request['checksum']}"
        )


async def initialize_checkpointer():
    global _checkpoint_connection, _checkpointer
    
    if _connection_factory is None:
        raise RuntimeError("local worker store is not initialized")
    
    connection = aiosqlite.Connection(_connection_factory, iter_chunk_size=64)
    await connection
    
    _checkpoint_connection = connection
    _checkpointer = AsyncSqliteSaver(connection)
    
    await _checkpointer.setup()


def get_checkpointer() -> AsyncSqliteSaver:
    if _checkpointer is None:
        raise RuntimeError("local checkpointer is not initialized")
    return _checkpointer


async def close_checkpointer() -> None:
    global _checkpoint_connection, _checkpointer

    if _checkpoint_connection is not None:
        await _checkpoint_connection.close()

    _checkpoint_connection = None
    _checkpointer = None

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


def update_profile_medical_summary(user_id: str, medical_summary: str) -> None:
    with _lock, _session() as db:
        row = db.get(Profile, str(user_id))
        if row is None:
            raise ValueError("User profile not found.")
        row.payload = {**row.payload, "medical_summary": medical_summary}
        db.commit()


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


def update_backend_session(user_id: str, username: str, access_token: str, refresh_token: str) -> None:
    with _lock, _session() as db:
        row = db.get(BackendSession, str(user_id))
        if row is None:
            db.add(BackendSession(
                user_id=str(user_id),
                username=username,
                access_token=access_token,
                refresh_token=refresh_token,
            ))
        else:
            row.username = username
            row.access_token = access_token
            row.refresh_token = refresh_token
        db.commit()


def get_backend_session(user_id: str) -> dict[str, str]:
    with _lock, _session() as db:
        row = db.get(BackendSession, str(user_id))
        if row is None:
            return {}
        return {
            "username": row.username,
            "access_token": row.access_token,
            "refresh_token": row.refresh_token,
        }


def has_backend_session(user_id: str) -> bool:
    with _lock, _session() as db:
        return db.get(BackendSession, str(user_id)) is not None


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

    medical_summary = profile.get("medical_summary")
    if medical_summary:
        lines.extend(["", "## Medical Summary", "", medical_summary])

    return "\n".join(lines)


def link_intake_session(chat_session_id: str | None, intake_id: str) -> None:
    if not chat_session_id:
        return
    with _lock, _session() as db:
        session = db.get(ChatSession, str(chat_session_id))
        if session is not None:
            session.intake_session_id = str(intake_id)
            db.commit()


def link_doctor_session(chat_session_id: str | None, doctor_session_id: str) -> None:
    if not chat_session_id:
        return
    with _lock, _session() as db:
        session = db.get(ChatSession, str(chat_session_id))
        if session is not None:
            session.doctor_session_id = str(doctor_session_id)
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
        _queue_profile_update(db, user_id, chat_session_id, delay_seconds=7 * 60)
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


def get_chat_session_data(user_id: str, chat_session_id: str) -> dict[str, Any] | None:
    with _lock, _session() as db:
        session = db.get(ChatSession, str(chat_session_id))
        if session is None or session.user_id != str(user_id):
            return None

        intake = db.get(Intake, session.intake_session_id) if session.intake_session_id else None
        research_sessions = db.scalars(
            select(Research)
            .where(
                Research.user_id == str(user_id),
                Research.chat_session_id == str(chat_session_id),
            )
            .order_by(Research.created_at)
        ).all()
        diagnosis = db.scalars(
            select(Diagnosis)
            .where(
                Diagnosis.user_id == str(user_id),
                Diagnosis.chat_session_id == str(chat_session_id),
            )
            .order_by(desc(Diagnosis.created_at))
            .limit(1)
        ).first()

        return {
            "id": session.id,
            "user_id": session.user_id,
            "intake_session": {
                "id": intake.id,
                "user_id": intake.user_id,
                "chief_complaint": intake.profile.get("chief_complaint"),
                "symptoms": intake.profile.get("symptoms", []),
                "red_flags": intake.profile.get("red_flags", []),
                "medical_summary": intake.profile.get("medical_summary"),
                "thread_id": intake.transcript,
                "status": "complete",
                "completed_at": intake.completed_at,
            } if intake else None,
            "research_sessions": [
                {
                    "id": row.id,
                    "user_id": row.user_id,
                    "chat_session_id": row.chat_session_id,
                    "triggered_by": row.triggered_by,
                    "research_effort": row.research_effort,
                    "research_report": row.research_report,
                    "citations": row.citations,
                }
                for row in research_sessions
            ],
            "diagnosis_session": {
                "id": diagnosis.id,
                "user_id": diagnosis.user_id,
                "intake_session_id": diagnosis.intake_session_id,
                "chat_session_id": diagnosis.chat_session_id,
                "report": diagnosis.report,
            } if diagnosis else None,
            "doctor_session_id": session.doctor_session_id,
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
        _queue_profile_update(db, user_id, chat_session_id)
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
        history = []
        for session in sessions:
            sections = list(session.sections or [])
            if session.doctor_session_id:
                sections.append({
                    "id": session.doctor_session_id,
                    "type": "doctor",
                    "title": "Doctor",
                    "created_at": None,
                    "content": f"## Doctor\n\n**Thread ID:** {session.doctor_session_id}\n\n_Full doctor transcripts are not saved yet._",
                })
            history.append({
                "id": session.id,
                "created_at": session.created_at,
                "sections": sections,
            })
        return history


def upsert_profile_update_job(
    user_id: str,
    chat_session_id: str | None,
    delay_seconds: float = 0,
) -> None:
    if not chat_session_id:
        return

    with _lock, _session() as db:
        _queue_profile_update(db, user_id, chat_session_id, delay_seconds)
        db.commit()


def _queue_profile_update(
    db: Session,
    user_id: str,
    chat_session_id: str | None,
    delay_seconds: float = 0,
) -> None:
    if not chat_session_id:
        return
    timestamp = time.time()
    row = db.get(ProfileUpdateJob, str(chat_session_id))
    if row is None:
        db.add(ProfileUpdateJob(
            chat_session_id=str(chat_session_id),
            user_id=str(user_id),
            dirty_at=timestamp,
            next_attempt_at=timestamp + delay_seconds,
        ))
        return
    if row.user_id != str(user_id):
        raise ValueError("Chat session belongs to another user.")
    row.dirty_at = timestamp
    row.next_attempt_at = timestamp + delay_seconds
    row.revision += 1
    row.attempts = 0
    row.last_error = None
    if row.status != "running":
        row.status = "pending"
        row.claimed_at = None


def claim_profile_update_job(lease_seconds: float = PROFILE_JOB_LEASE_SECONDS) -> dict[str, Any] | None:
    timestamp = time.time()
    with _lock, _session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        for stale in db.scalars(select(ProfileUpdateJob).where(
            ProfileUpdateJob.status == "running",
            ProfileUpdateJob.claimed_at <= timestamp - lease_seconds,
        )):
            stale.status = "pending"
            stale.claimed_at = None

        running_users = select(ProfileUpdateJob.user_id).where(ProfileUpdateJob.status == "running")
        row = db.scalars(
            select(ProfileUpdateJob)
            .where(
                ProfileUpdateJob.status == "pending",
                ProfileUpdateJob.next_attempt_at <= timestamp,
                ProfileUpdateJob.user_id.not_in(running_users),
            )
            .order_by(ProfileUpdateJob.next_attempt_at, ProfileUpdateJob.dirty_at)
            .limit(1)
        ).first()
        if row is None:
            db.commit()
            return None

        row.status = "running"
        row.claimed_at = timestamp
        job = {
            "user_id": row.user_id,
            "chat_session_id": row.chat_session_id,
            "revision": row.revision,
        }
        db.commit()
        return job


def complete_profile_update_job(chat_session_id: str, revision: int) -> None:
    with _lock, _session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        row = db.get(ProfileUpdateJob, str(chat_session_id))
        if row is None:
            db.commit()
            return
        if row.revision == revision:
            db.delete(row)
        else:
            row.status = "pending"
            row.claimed_at = None
        db.commit()


def fail_profile_update_job(chat_session_id: str, revision: int, error: str) -> None:
    with _lock, _session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        row = db.get(ProfileUpdateJob, str(chat_session_id))
        if row is None:
            db.commit()
            return
        row.status = "pending"
        row.claimed_at = None
        if row.revision == revision:
            row.attempts += 1
            row.next_attempt_at = time.time() + min(3600, 30 * (2 ** (row.attempts - 1)))
            row.last_error = error[-2000:]
        db.commit()


def next_profile_update_delay() -> float | None:
    with _lock, _session() as db:
        claimed_at = db.scalars(
            select(ProfileUpdateJob.claimed_at)
            .where(ProfileUpdateJob.status == "running")
            .order_by(ProfileUpdateJob.claimed_at)
            .limit(1)
        ).first()
        if claimed_at is not None:
            return max(0, claimed_at + PROFILE_JOB_LEASE_SECONDS - time.time())
        next_attempt = db.scalars(
            select(ProfileUpdateJob.next_attempt_at)
            .where(ProfileUpdateJob.status == "pending")
            .order_by(ProfileUpdateJob.next_attempt_at)
            .limit(1)
        ).first()
        return max(0, next_attempt - time.time()) if next_attempt is not None else None


def has_pending_profile_update_jobs() -> bool:
    with _lock, _session() as db:
        return db.scalars(
            select(ProfileUpdateJob.chat_session_id)
            .where(ProfileUpdateJob.status == "pending")
            .limit(1)
        ).first() is not None
