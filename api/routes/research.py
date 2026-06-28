from typing import AsyncIterable, Literal
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.sse import EventSourceResponse
from pydantic import BaseModel

from api.shared import clear_encryption_context, get_user_id_or_400, require_encryption_context
from api.services.research_service import get_citation_text, stream_research as stream_research_service

router = APIRouter()


class ResearchRequest(BaseModel):
    intake_id: UUID
    session_id: UUID | None = None
    research_effort: Literal["fast", "standard", "deep", "web"] = "standard"


class CitationTextRequest(BaseModel):
    research_session_id: UUID
    citation_num: int


@router.post('/research', response_class=EventSourceResponse)
async def stream_research(research_request: ResearchRequest, request: Request) -> AsyncIterable:
    user_id = get_user_id_or_400(request)
    token = require_encryption_context(request)
    try:
        async for event in stream_research_service(
            research_request.intake_id,
            user_id,
            research_request.session_id,
            research_request.research_effort,
        ):
            yield event
    finally:
        clear_encryption_context(token)


@router.post('/research/citation')
async def citation_text(citation_request: CitationTextRequest, request: Request):
    user_id = get_user_id_or_400(request)
    token = require_encryption_context(request)
    try:
        return {"text": await get_citation_text(citation_request.research_session_id, citation_request.citation_num, user_id)}
    finally:
        clear_encryption_context(token)
