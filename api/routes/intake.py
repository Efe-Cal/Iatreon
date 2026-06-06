from typing import AsyncIterable

from fastapi import APIRouter, Request
from fastapi.sse import EventSourceResponse

from api.shared import get_user_id_or_400, ChatRequest

from api.services.intake_service import stream_intake_chat

router = APIRouter()

@router.post("/chat/intake", response_class=EventSourceResponse)
async def stream_intake_chat(chat_request: ChatRequest, request: Request) -> AsyncIterable:
    user_id = get_user_id_or_400(request)
    return EventSourceResponse(stream_intake_chat(chat_request, user_id))