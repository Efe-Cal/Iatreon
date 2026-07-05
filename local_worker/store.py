import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_lock = threading.Lock()


def _state_path() -> Path:
    configured = os.getenv("IATREON_LOCAL_WORKER_STATE")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[1] / "data" / "local_worker_state.json"


def _empty_state() -> dict[str, Any]:
    return {
        "profiles": {},
        "sessions": {},
        "intakes": {},
        "research": {},
        "diagnoses": {},
        "doctor": {},
    }


def _read_state() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return _empty_state()
    try:
        with path.open("r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        return _empty_state()
    empty = _empty_state()
    empty.update(state)
    return empty


def _write_state(state: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, default=str)
    tmp.replace(path)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_session(user_id: str) -> str:
    with _lock:
        state = _read_state()
        session_id = str(uuid.uuid4())
        state["sessions"][session_id] = {
            "id": session_id,
            "user_id": str(user_id),
            "created_at": now(),
            "sections": [],
        }
        _write_state(state)
        return session_id


def update_profile(profile: dict[str, Any]) -> None:
    with _lock:
        state = _read_state()
        user_id = str(profile["user_id"])
        state["profiles"][user_id] = profile
        _write_state(state)


def get_profile(user_id: str) -> dict[str, Any]:
    with _lock:
        return _read_state()["profiles"].get(str(user_id), {})


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
    with _lock:
        state = _read_state()
        session = state["sessions"].get(str(chat_session_id))
        if session is not None:
            session["intake_session_id"] = str(intake_id)
            _write_state(state)


def save_intake(user_id: str, intake_id: str, chat_session_id: str | None, profile: dict[str, Any], transcript: str) -> None:
    completed_at = now()
    record = {
        "id": str(intake_id),
        "user_id": str(user_id),
        "chat_session_id": str(chat_session_id) if chat_session_id else None,
        "profile": profile,
        "transcript": transcript,
        "completed_at": completed_at,
    }
    with _lock:
        state = _read_state()
        state["intakes"][str(intake_id)] = record
        session = state["sessions"].get(str(chat_session_id)) if chat_session_id else None
        if session is not None:
            sections = [s for s in session.get("sections", []) if s.get("id") != str(intake_id)]
            sections.append({
                "id": str(intake_id),
                "type": "intake",
                "title": profile.get("chief_complaint") or "Intake",
                "created_at": completed_at,
                "content": profile.get("medical_summary") or "_No intake summary saved._",
            })
            session["sections"] = sections
            session["intake_session_id"] = str(intake_id)
        _write_state(state)


def get_intake(intake_id: str) -> dict[str, Any] | None:
    with _lock:
        return _read_state()["intakes"].get(str(intake_id))


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
    record = {
        "id": str(research_id),
        "user_id": str(user_id),
        "chat_session_id": str(chat_session_id) if chat_session_id else None,
        "triggered_by": triggered_by,
        "research_effort": research_effort,
        "research_report": report,
        "citations": normalized_citations,
        "created_at": created_at,
    }
    with _lock:
        state = _read_state()
        state["research"][str(research_id)] = record
        session = state["sessions"].get(str(chat_session_id)) if chat_session_id else None
        if session is not None:
            sections = [s for s in session.get("sections", []) if s.get("id") != str(research_id)]
            sections.append({
                "id": str(research_id),
                "type": "research",
                "title": f"Research ({research_effort})",
                "created_at": created_at,
                "content": report or "_No research report saved._",
                "citations": normalized_citations,
            })
            session["sections"] = sections
        _write_state(state)


def get_latest_research(user_id: str, chat_session_id: str | None, triggered_by: str = "user") -> dict[str, Any] | None:
    with _lock:
        rows = [
            row for row in _read_state()["research"].values()
            if str(row.get("user_id")) == str(user_id)
            and str(row.get("chat_session_id")) == str(chat_session_id)
            and row.get("triggered_by") == triggered_by
        ]
    rows.sort(key=lambda row: row.get("created_at") or "", reverse=True)
    return rows[0] if rows else None


def save_diagnosis(user_id: str, diagnosis_id: str, intake_id: str, chat_session_id: str | None, report: dict[str, Any]) -> None:
    created_at = now()
    record = {
        "id": str(diagnosis_id),
        "user_id": str(user_id),
        "intake_session_id": str(intake_id),
        "chat_session_id": str(chat_session_id) if chat_session_id else None,
        "report": report,
        "created_at": created_at,
    }
    with _lock:
        state = _read_state()
        state["diagnoses"][str(diagnosis_id)] = record
        session = state["sessions"].get(str(chat_session_id)) if chat_session_id else None
        if session is not None:
            sections = [s for s in session.get("sections", []) if s.get("id") != str(diagnosis_id)]
            sections.append({
                "id": str(diagnosis_id),
                "type": "diagnosis",
                "title": "Diagnosis",
                "created_at": created_at,
                "content": report,
            })
            session["sections"] = sections
        _write_state(state)


def get_citation_text(research_id: str, citation_num: int) -> str:
    with _lock:
        research = _read_state()["research"].get(str(research_id)) or {}
    citation = (research.get("citations") or {}).get(str(citation_num)) or {}
    return citation.get("text") or citation.get("full_text") or ""


def list_history(user_id: str) -> list[dict[str, Any]]:
    with _lock:
        sessions = [
            session
            for session in _read_state()["sessions"].values()
            if str(session.get("user_id")) == str(user_id)
        ]
    sessions.sort(key=lambda s: s.get("created_at") or "", reverse=True)
    return [
        {
            "id": session["id"],
            "created_at": session.get("created_at"),
            "sections": session.get("sections", []),
        }
        for session in sessions
    ]
