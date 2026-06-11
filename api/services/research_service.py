from typing import AsyncIterable
from db.db import SessionLocal
from db.models import IntakeSession, ResearchSession
from db.repositories import IntakeRepo, ResearchRepo
from agents.research import ResearchAgent
from fastapi import HTTPException
from uuid import UUID

async def stream_research(intake_id: UUID, user_id) -> AsyncIterable:
    async with SessionLocal() as session:
        research_repo = ResearchRepo(session, user_id)
        intake_session: IntakeSession = await IntakeRepo(session, user_id).get_session(intake_id)

        if not intake_session:
            raise HTTPException(status_code=404, detail="Intake session not found.")
        
        research_session: ResearchSession = await research_repo.create_research_session(intake_session.id)
        research_agent = ResearchAgent(session, research_repo, research_session.id)
        async for research_chunk in research_agent.run(intake_session):
            if isinstance(research_chunk, dict):
                yield research_chunk

            elif isinstance(research_chunk, tuple) and len(research_chunk) == 2:
                research_report, citations = research_chunk
                await research_repo.update_research_session(
                    session_id=research_session.id,
                    research_report=research_report,
                    citations=citations,
                )
                print("Research complete, yielding final result...")
                yield {
                    "type": "research_complete",
                    "data": {"report": research_report, "citations": citations},
                }