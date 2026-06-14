from typing import AsyncIterable
from db.db import unit_of_work
from db.models import IntakeSession, ResearchSession
from db.repositories import IntakeRepo, ResearchRepo
from agents.research import ResearchAgent
from fastapi import HTTPException
from uuid import UUID

async def stream_research(intake_id: UUID, user_id) -> AsyncIterable:
    async with unit_of_work() as db:
        research_repo = ResearchRepo(user_id)
        intake_session: IntakeSession = await IntakeRepo(user_id).get_session(db, intake_id)

        if not intake_session:
            raise HTTPException(status_code=404, detail="Intake session not found.")
        
        research_session: ResearchSession = await research_repo.create_research_session(db, intake_session.id)
        research_agent = ResearchAgent(research_repo, research_session.id)
        async for research_chunk in research_agent.run(intake_session):
            if isinstance(research_chunk, dict):
                yield research_chunk

            elif isinstance(research_chunk, tuple) and len(research_chunk) == 2:
                research_report, citations = research_chunk
                await research_repo.update_research_session(
                    db,
                    session_id=research_session.id,
                    research_report=research_report,
                    citations=citations,
                )

                citation_payload = citations if isinstance(citations, dict) else {}
                print("Research complete, yielding final result...")
                yield {
                    "type": "research_complete",
                    "data": {"report": research_report, "citations": citation_payload},
                }