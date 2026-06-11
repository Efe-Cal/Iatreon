from typing import AsyncIterable

from fastapi import APIRouter, Request
from fastapi.sse import EventSourceResponse

from api.shared import get_user_id_or_400
from api.services.research_service import stream_research as stream_research_service

router = APIRouter()

@router.post("/research", response_class=EventSourceResponse)
async def stream_research(intake_id: str, request: Request) -> AsyncIterable:
    user_id = get_user_id_or_400(request)
    async for event in stream_research_service(intake_id.replace("-", ""), user_id):
        yield event