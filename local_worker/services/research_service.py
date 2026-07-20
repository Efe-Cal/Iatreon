from typing import AsyncIterable
from uuid import uuid4

from agents.research import ResearchAgent, ResearchEffort
from local_worker.errors import NotFoundError
from local_worker.store import conversation_session as store
from local_worker.models import CitationTextRequest, ResearchRequest
from db.schemas import IntakeSessionData


async def stream_research(req: ResearchRequest) -> AsyncIterable:
    intake_id = req.intake_id
    user_id = req.user_id
    session_id = req.session_id
    research_effort: ResearchEffort = req.research_effort

    intake_record = store.get_intake(str(intake_id))
    if not intake_record:
        raise NotFoundError("Intake session not found.")

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

    research_agent = ResearchAgent(None, research_session_id, effort=research_effort)
    async for research_chunk in research_agent.run(intake_session):
        if isinstance(research_chunk, dict):
            yield research_chunk

        elif isinstance(research_chunk, tuple) and len(research_chunk) == 2:
            research_report, citations = research_chunk
            store.save_research(
                str(user_id),
                str(research_session_id),
                str(chat_session_id) if chat_session_id else None,
                research_effort,
                research_report,
                citations if isinstance(citations, dict) else {},
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
    local_text = store.get_citation_text(str(research_session_id), citation_num)
    if local_text:
        return local_text
    raise NotFoundError("Citation not found.")
