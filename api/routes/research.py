from typing import AsyncIterable

from fastapi import APIRouter, Request
from fastapi.sse import EventSourceResponse

from api.shared import get_user_id_or_400
from api.services.research_service import stream_research

router = APIRouter()

@router.post("/research", response_class=EventSourceResponse)
def stream_research(intake_id: str, request: Request) -> AsyncIterable:
    user_id = get_user_id_or_400(request)
    return EventSourceResponse(stream_research(intake_id, user_id))