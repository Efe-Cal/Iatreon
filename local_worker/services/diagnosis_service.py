from typing import AsyncIterable
from uuid import uuid4

from local_worker.errors import NotFoundError
from local_worker import store
from db.schemas import IntakeSessionData, ResearchSessionData
from agents.diagnosis import DiagnosisAgent
from models import DiagnosisRequest

async def stream_diagnosis(req: DiagnosisRequest) -> AsyncIterable:
    intake_id = req.intake_id
    user_id = str(req.user_id)
    session_id = req.session_id

    intake_record = store.get_intake(str(intake_id))
    if not intake_record:
        raise NotFoundError("Intake session not found.")

    profile = intake_record.get("profile") or {}
    intake_session = IntakeSessionData(
        id=intake_id,
        user_id=req.user_id,
        chief_complaint=profile.get("chief_complaint"),
        symptoms=profile.get("symptoms", []),
        red_flags=profile.get("red_flags", []),
        medical_summary=profile.get("medical_summary"),
        thread_id=str(intake_record.get("transcript") or ""),
        status="complete",
        completed_at=intake_record.get("completed_at"),
    )
    chat_session_id = session_id
    research_record = store.get_latest_research(user_id, str(session_id) if session_id else None)
    research_session = None
    if research_record:
        research_session = ResearchSessionData(
            id=research_record["id"],
            user_id=req.user_id,
            chat_session_id=session_id,
            triggered_by=research_record.get("triggered_by") or "user",
            research_effort=research_record.get("research_effort") or "standard",
            research_report=research_record.get("research_report"),
            citations=research_record.get("citations") or {},
        )

    diagnosis_agent = DiagnosisAgent(intake_session, research_session, chat_session_id)
    async for diagnosis_chunk in diagnosis_agent.diagnose():
        if isinstance(diagnosis_chunk, dict) and diagnosis_chunk.get("type") == "error":
            yield diagnosis_chunk
            return

        report = diagnosis_chunk if isinstance(diagnosis_chunk, dict) else {"content": diagnosis_chunk}
        diagnosis_id = uuid4()
        store.save_diagnosis(user_id, str(diagnosis_id), str(intake_session.id), str(chat_session_id) if chat_session_id else None, report)
        yield {
            "type": "diagnosis_complete",
            "data": {
                "report": diagnosis_chunk,
                "diagnosis_session_id": str(diagnosis_id),
            },
        }
