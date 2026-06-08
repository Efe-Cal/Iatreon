from typing import AsyncIterable
from fastapi import APIRouter, Request
from fastapi.sse import EventSourceResponse

from api.shared import get_user_id_or_400
from api.services.diagnosis_service import stream_diagnosis as stream_diagnosis_service

router = APIRouter()

@router.post("/diagnose", response_class=EventSourceResponse)
async def stream_diagnosis(intake_id: str, request: Request) -> AsyncIterable:
    user_id = get_user_id_or_400(request)
    async for event in stream_diagnosis_service(intake_id, user_id):
        yield event