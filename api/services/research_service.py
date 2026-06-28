from typing import AsyncIterable
from uuid import UUID

from agents.research import ResearchAgent, ResearchEffort
from db.db import read_only_session, unit_of_work
from db.models import ResearchSession
from db.repositories import ArticleRepo, BookSectionRepo, IntakeRepo, ResearchRepo, SessionRepo, WebSearchResultRepo
from db.schemas import IntakeSessionData
from fastapi import HTTPException


async def stream_research(intake_id: UUID, user_id: UUID, session_id: UUID | None = None, research_effort: ResearchEffort = "standard") -> AsyncIterable:
    research_repo = ResearchRepo(user_id)

    async with unit_of_work() as db:
        intake_session: IntakeSessionData = await IntakeRepo(user_id).get_session(db, intake_id)

        if not intake_session:
            raise HTTPException(status_code=404, detail="Intake session not found.")

        chat_session_id = None
        if session_id is not None:
            chat_session = await SessionRepo().get_session(db, user_id, session_id)
            if chat_session is None:
                raise HTTPException(status_code=404, detail="Chat session not found.")
            chat_session_id = chat_session.id

        research_session: ResearchSession = await research_repo.create_research_session(
            db,
            chat_session_id,
            triggered_by="user",
            research_effort=research_effort,
        )
        research_session_id = research_session.id

    research_agent = ResearchAgent(research_repo, research_session_id, effort=research_effort)
    async for research_chunk in research_agent.run(intake_session):
        if isinstance(research_chunk, dict):
            yield research_chunk

        elif isinstance(research_chunk, tuple) and len(research_chunk) == 2:
            research_report, citations = research_chunk
            async with unit_of_work() as db:
                await research_repo.update_research_session(
                    db,
                    session_id=research_session_id,
                    research_report=research_report,
                    citations=citations,
                )

            citation_payload = citations if isinstance(citations, dict) else {}
            print("Research complete, yielding final result...")
            yield {
                "type": "research_complete",
                "data": {
                    "report": research_report,
                    "citations": citation_payload,
                    "research_session_id": str(research_session_id),
                    "triggered_by": "user",
                    "research_effort": research_effort,
                },
            }


async def get_citation_text(research_session_id: UUID, citation_num: int, user_id) -> str:
    async with read_only_session() as db:
        research = await ResearchRepo(user_id).get_research_session(db, research_session_id)
        if not research:
            raise HTTPException(status_code=404, detail="Research session not found.")

        citation = research.citations.get(citation_num) or research.citations.get(str(citation_num))
        if not citation:
            raise HTTPException(status_code=404, detail="Citation not found.")

        if not citation.get("id"):
            raise HTTPException(status_code=404, detail="Citation source not found.")

        source_id = UUID(str(citation["id"]))
        source_type = citation.get("type")

        if source_type == "article":
            article = await ArticleRepo().get_article_by_id(db, source_id)
            if article:
                return "\n\n".join(part for part in [article.abstract, article.full_text] if part)

        if source_type == "book_section":
            section = await BookSectionRepo().get_book_section_by_id(db, source_id)
            if section:
                return section.text or ""

        if source_type == "web_search_result":
            result = await WebSearchResultRepo().get_web_search_result_by_id(db, source_id)
            if result:
                return "\n\n".join(part for part in [result.highlights, result.full_content] if part)

    return ""
