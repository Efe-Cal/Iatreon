from fastapi import APIRouter
from fastapi.sse import EventSourceResponse

from api.shared import get_user_id_or_400
from api.services.diagnosis_service import stream_diagnosis

router = APIRouter()

@router.post("/diagnose", response_class=EventSourceResponse)
def stream_diagnosis(intake_id: str, request) -> EventSourceResponse:
    user_id = get_user_id_or_400(request)
    return EventSourceResponse(stream_diagnosis(intake_id, request))