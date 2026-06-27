from typing import AsyncIterable

from db.db import read_only_session
from db.repositories import IntakeRepo, ResearchRepo
from db.schemas import IntakeSessionData
from agents.diagnosis import DiagnosisAgent

from fastapi import HTTPException

async def stream_diagnosis(intake_id: str, user_id: str) -> AsyncIterable:

    async with read_only_session() as db:
        intake_session: IntakeSessionData = await IntakeRepo(user_id).get_session(db,intake_id)
        if not intake_session:
            raise HTTPException(status_code=404, detail="Intake session not found.")

        if str(intake_session.user_id) != str(user_id):
            raise HTTPException(status_code=403, detail="Forbidden: You do not have access to this intake session.")

        research_session = await ResearchRepo(user_id).get_research_session_by_intake_id(
            db,
            intake_session.id,
            triggered_by="user",
        )

    diagnosis_agent = DiagnosisAgent(intake_session, research_session)
    async for diagnosis_chunk in diagnosis_agent.diagnose():
        yield {"type": "diagnosis_complete", "data": {"report": diagnosis_chunk}}
