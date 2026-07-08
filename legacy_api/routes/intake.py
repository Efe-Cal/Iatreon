from typing import AsyncIterable

from fastapi import APIRouter, Request
from fastapi.sse import EventSourceResponse

from legacy_api.shared import ChatRequest, clear_encryption_context, get_user_id_or_400, require_encryption_context
from legacy_api.services.intake_service import stream_intake_chat as stream_intake_chat_service

router = APIRouter()


@router.post('/chat/intake', response_class=EventSourceResponse)
async def stream_intake_chat(chat_request: ChatRequest, request: Request) -> AsyncIterable:
    user_id = get_user_id_or_400(request)
    token = require_encryption_context(request)
    try:
        async for event in stream_intake_chat_service(chat_request, user_id):
            yield event
    finally:
        clear_encryption_context(token)
