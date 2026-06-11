from typing import AsyncIterable

from db.db import SessionLocal
from db.models import IntakeSession
from db.repositories import IntakeRepo, ResearchRepo
from agents.diagnosis import DiagnosisAgent

from fastapi import HTTPException

async def stream_diagnosis(intake_id: str, user_id: str) -> AsyncIterable:

    async with SessionLocal() as session:
        intake_session: IntakeSession = await IntakeRepo(session, user_id).get_session(intake_id)
        if not intake_session:
            raise HTTPException(status_code=404, detail="Intake session not found.")

        if intake_session.user_id != user_id:
            raise HTTPException(status_code=403, detail="Forbidden: You do not have access to this intake session.")

        research_session = await ResearchRepo(session, user_id).get_research_session_by_intake_id(intake_session.id)
        diagnosis_agent = DiagnosisAgent(intake_session, research_session)
        async for diagnosis_chunk in diagnosis_agent.diagnose():
            yield {"event": "diagnosis_complete", "data": {"report": diagnosis_chunk}}