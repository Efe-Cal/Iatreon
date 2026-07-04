from typing import AsyncIterable

from fastapi import APIRouter, Depends, Request
from fastapi.sse import EventSourceResponse

from api.security import AuthContext, require_auth
from api.shared import ChatRequest, clear_encryption_context, require_encryption_context
from api.services.intake_service import stream_intake_chat as stream_intake_chat_service

router = APIRouter()


@router.post('/chat/intake', response_class=EventSourceResponse)
async def stream_intake_chat(
    chat_request: ChatRequest,
    request: Request,
    auth: AuthContext = Depends(require_auth),
) -> AsyncIterable:
    user_id = str(auth.user_id)
    token = require_encryption_context(request)
    try:
        async for event in stream_intake_chat_service(chat_request, user_id):
            yield event
    finally:
        clear_encryption_context(token)
