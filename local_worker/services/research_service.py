from typing import AsyncIterable
from uuid import UUID, uuid4

from agents.research import ResearchAgent, ResearchEffort
from local_worker import store
from models import CitationTextRequest, ResearchRequest
from db.db import read_only_session, unit_of_work
from db.models import ResearchSession
from db.repositories import ArticleRepo, BookSectionRepo, IntakeRepo, ResearchRepo, SessionRepo, WebSearchResultRepo
from db.schemas import IntakeSessionData
from fastapi import HTTPException


async def stream_research(req: ResearchRequest) -> AsyncIterable:
    intake_id = req.intake_id
    user_id = req.user_id
    session_id = req.session_id
    research_effort: ResearchEffort = req.research_effort
    research_repo = ResearchRepo(str(user_id))

    intake_record = store.get_intake(str(intake_id))
    if intake_record:
        profile = intake_record.get("profile") or {}
        intake_session = IntakeSessionData(
            id=intake_id,
            user_id=user_id,
            chief_complaint=profile.get("chief_complaint"),
            symptoms=profile.get("symptoms", []),
            red_flags=profile.get("red_flags", []),
            medical_summary=profile.get("medical_summary"),
            thread_id=str(intake_record.get("transcript") or ""),
            status="complete",
            completed_at=intake_record.get("completed_at"),
        )
        chat_session_id = session_id
        research_session_id = uuid4()
    else:
        async with unit_of_work() as db:
            intake_session: IntakeSessionData = await IntakeRepo(str(user_id)).get_session(db, intake_id)

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
            if intake_record:
                store.save_research(
                    str(user_id),
                    str(research_session_id),
                    str(chat_session_id) if chat_session_id else None,
                    research_effort,
                    research_report,
                    citations if isinstance(citations, dict) else {},
                )
            else:
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
                    "source_warnings": research_agent.source_warnings,
                    "research_session_id": str(research_session_id),
                    "triggered_by": "user",
                    "research_effort": research_effort,
                },
            }


async def get_citation_text(req: CitationTextRequest) -> str:
    research_session_id = req.research_session_id
    citation_num = req.citation_num
    user_id = req.user_id
    local_text = store.get_citation_text(str(research_session_id), citation_num)
    if local_text:
        return local_text
    async with read_only_session() as db:
        research = await ResearchRepo(str(user_id)).get_research_session(db, research_session_id)
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
