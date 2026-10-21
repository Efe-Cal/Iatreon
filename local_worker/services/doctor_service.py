import uuid
from typing import AsyncIterable

from local_worker import store
from local_worker.errors import NotFoundError
from local_worker.models import ChatRequest

from agents.doctor import DoctorAgent

async def stream_doctor_chat_service(chat_request: ChatRequest) -> AsyncIterable[dict]:
    user_id = str(chat_request.user_id)

    if chat_request.session_id:
        chat_session = store.get_chat_session_data(user_id, str(chat_request.session_id))
        if chat_session is None:
            raise NotFoundError("Chat session not found.")
        linked_id = chat_session.get("doctor_session_id")
        if linked_id:
            linked_id = uuid.UUID(str(linked_id))
            if chat_request.conversation_id and chat_request.conversation_id != linked_id:
                raise NotFoundError("Doctor conversation not found.")
            chat_request.conversation_id = linked_id
        else:
            chat_request.conversation_id = uuid.uuid4()
            store.link_doctor_session(user_id, str(chat_request.session_id), str(chat_request.conversation_id))
    else:
        chat_request.conversation_id = uuid.uuid4()

    doctor_agent = DoctorAgent(user_id=user_id, chat_session_id=chat_request.session_id)
    
    yield {"type": "session_started", "session_id": chat_request.session_id, "conversation_id": chat_request.conversation_id}

    failed = False
    async for event in doctor_agent.run_doctor(chat_request.message, chat_request.conversation_id):
        if isinstance(event, dict) and event.get("type") == "error":
            failed = True
        yield event

    if not failed:
        store.upsert_profile_update_job(
            user_id,
            str(chat_request.session_id) if chat_request.session_id else None,
            delay_seconds=2 * 60,
        )
