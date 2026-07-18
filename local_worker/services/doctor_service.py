import uuid
from typing import AsyncIterable

from local_worker import store
from local_worker.models import ChatRequest

from agents.doctor import DoctorAgent

async def stream_doctor_chat_service(chat_request: ChatRequest) -> AsyncIterable[dict]:
    user_id = str(chat_request.user_id)

    if not chat_request.conversation_id:
        chat_request.conversation_id = uuid.uuid4()

    store.link_doctor_session(
        str(chat_request.session_id) if chat_request.session_id else None,
        str(chat_request.conversation_id),
    )
    
    doctor_agent = DoctorAgent(user_id=user_id, chat_session_id=chat_request.session_id)
    
    yield {"type": "session_started", "session_id": chat_request.session_id, "conversation_id": chat_request.conversation_id}

    async for event in doctor_agent.run_doctor(chat_request.message, chat_request.conversation_id):
        yield event
