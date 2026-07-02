from typing import AsyncIterable

from db.db import read_only_session, unit_of_work
from db.repositories import DiagnosisRepo, IntakeRepo, ResearchRepo, SessionRepo
from db.schemas import IntakeSessionData
from agents.diagnosis import DiagnosisAgent

from fastapi import HTTPException

async def stream_diagnosis(intake_id: str, user_id: str, session_id: str | None = None) -> AsyncIterable:

    async with read_only_session() as db:
        intake_session: IntakeSessionData = await IntakeRepo(user_id).get_session(db,intake_id)
        if not intake_session:
            raise HTTPException(status_code=404, detail="Intake session not found.")

        if str(intake_session.user_id) != str(user_id):
            raise HTTPException(status_code=403, detail="Forbidden: You do not have access to this intake session.")

        chat_session_id = None
        research_session = None
        if session_id is not None:
            chat_session = await SessionRepo().get_session(db, user_id, session_id)
            if chat_session is None:
                raise HTTPException(status_code=404, detail="Chat session not found.")
            chat_session_id = chat_session.id
            research_session = await ResearchRepo(user_id).get_latest_research_session_by_chat_id(
                db,
                chat_session.id,
                triggered_by="user",
            )

    diagnosis_agent = DiagnosisAgent(intake_session, research_session, chat_session_id)
    async for diagnosis_chunk in diagnosis_agent.diagnose():
        if isinstance(diagnosis_chunk, dict) and diagnosis_chunk.get("type") == "error":
            yield diagnosis_chunk
            return

        async with unit_of_work() as db:
            diagnosis_session = await DiagnosisRepo(user_id).create_diagnosis_session(
                db,
                intake_session.id,
                diagnosis_chunk if isinstance(diagnosis_chunk, dict) else {"content": diagnosis_chunk},
                chat_session_id,
            )
        yield {
            "type": "diagnosis_complete",
            "data": {
                "report": diagnosis_chunk,
                "diagnosis_session_id": str(diagnosis_session.id),
            },
        }
