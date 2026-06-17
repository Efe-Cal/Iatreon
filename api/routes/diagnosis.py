from typing import AsyncIterable
from uuid import UUID
from fastapi import APIRouter, Request
from fastapi.sse import EventSourceResponse
from pydantic import BaseModel

from api.shared import get_user_id_or_400
from api.services.diagnosis_service import stream_diagnosis as stream_diagnosis_service

router = APIRouter()

class DiagnosisRequest(BaseModel):
    intake_id: UUID
    session_id: UUID

@router.post("/diagnose", response_class=EventSourceResponse)
async def stream_diagnosis(diagnosis_request: DiagnosisRequest, request: Request) -> AsyncIterable:
    user_id = get_user_id_or_400(request)
    async for event in stream_diagnosis_service(diagnosis_request.intake_id, user_id):
        yield event