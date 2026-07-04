from typing import AsyncIterable
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.sse import EventSourceResponse
from pydantic import BaseModel

from api.security import AuthContext, require_auth
from api.shared import clear_encryption_context, require_encryption_context
from api.services.diagnosis_service import stream_diagnosis as stream_diagnosis_service

router = APIRouter()


class DiagnosisRequest(BaseModel):
    intake_id: UUID
    session_id: UUID | None = None


@router.post('/diagnose', response_class=EventSourceResponse)
async def stream_diagnosis(
    diagnosis_request: DiagnosisRequest,
    request: Request,
    auth: AuthContext = Depends(require_auth),
) -> AsyncIterable:
    user_id = str(auth.user_id)
    token = require_encryption_context(request)
    try:
        async for event in stream_diagnosis_service(diagnosis_request.intake_id, user_id, diagnosis_request.session_id):
            yield event
    finally:
        clear_encryption_context(token)
