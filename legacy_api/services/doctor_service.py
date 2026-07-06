import uuid
from typing import AsyncIterable

from legacy_api.shared import ChatRequest

from agents.doctor import DoctorAgent

from db.models import DoctorSession
from db.repositories import DoctorRepo
from db.db import unit_of_work

async def stream_doctor_chat_service(chat_request: ChatRequest, user_id: str) -> AsyncIterable[dict]:
    
    doctor_repo = DoctorRepo()

    if not chat_request.conversation_id:
        chat_request.conversation_id = uuid.uuid4()
    
    doctor_agent = DoctorAgent(user_id=user_id, chat_session_id=chat_request.session_id)
    
    async with unit_of_work() as db:
        doctor_session: DoctorSession = await doctor_repo.get_or_create_doctor_session(
            db,
            user_id,
            chat_request.session_id,
            chat_request.conversation_id,
        )
    
    yield {"type": "session_started", "session_id": chat_request.session_id, "conversation_id": chat_request.conversation_id}

    async for event in doctor_agent.run_doctor(chat_request.message, chat_request.conversation_id):
        yield event
