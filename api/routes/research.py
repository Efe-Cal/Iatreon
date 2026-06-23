from typing import AsyncIterable
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.sse import EventSourceResponse
from pydantic import BaseModel

from api.shared import clear_encryption_context, get_user_id_or_400, require_encryption_context
from api.services.research_service import stream_research as stream_research_service

router = APIRouter()

class ResearchRequest(BaseModel):
    intake_id: UUID


@router.post('/research', response_class=EventSourceResponse)
async def stream_research(research_request: ResearchRequest, request: Request) -> AsyncIterable:
    user_id = get_user_id_or_400(request)
    token = require_encryption_context(request)
    try:
        async for event in stream_research_service(research_request.intake_id, user_id):
            yield event
    finally:
        clear_encryption_context(token)
