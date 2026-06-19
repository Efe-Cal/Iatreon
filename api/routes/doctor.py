from typing import AsyncIterable

from fastapi import APIRouter, Request
from fastapi.sse import EventSourceResponse

from api.shared import get_user_id_or_400, ChatRequest

from api.services.doctor_service import stream_doctor_chat_service

router = APIRouter()

@router.post("/chat/doctor", response_class=EventSourceResponse)
async def stream_doctor_chat(chat_request: ChatRequest, request: Request) -> AsyncIterable:
    user_id = get_user_id_or_400(request)
    async for event in stream_doctor_chat_service(chat_request, user_id):
        yield event