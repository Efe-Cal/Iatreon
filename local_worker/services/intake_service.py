import uuid
from typing import AsyncIterable

from local_worker.models import ChatRequest
from agents.intake import run_intake_cli
from local_worker.store import conversation_session as store
from local_worker.errors import NotFoundError

from db.schemas import IntakeProfile

async def stream_intake_chat(chat_request: ChatRequest) -> AsyncIterable[dict]:
    user_id = str(chat_request.user_id)

    if chat_request.session_id:
        chat_session = store.get_chat_session_data(user_id, str(chat_request.session_id))
        if chat_session is None:
            raise NotFoundError("Chat session not found.")
        linked_intake_id = chat_session.get("intake_session_id")
        if linked_intake_id:
            linked_id = uuid.UUID(str(linked_intake_id))
            if chat_request.conversation_id and chat_request.conversation_id != linked_id:
                raise NotFoundError("Chat session with linked intake not found.")
            chat_request.conversation_id = linked_id
        else:
            chat_request.conversation_id = uuid.uuid4()
            store.link_intake_session(user_id, str(chat_request.session_id), str(chat_request.conversation_id))
    else:
        chat_request.conversation_id = uuid.uuid4()

    intake_session_id = chat_request.conversation_id
    
    yield {"type": "session_started", "session_id": chat_request.session_id, "conversation_id": intake_session_id}
    
    async for chunk in run_intake_cli(chat_request.message, str(intake_session_id), user_id):
        if isinstance(chunk, tuple) and len(chunk) == 2 and isinstance(chunk[0], IntakeProfile):
            profile = chunk[0].model_dump() if hasattr(chunk[0], "model_dump") else chunk[0]
            store.save_intake(user_id, str(intake_session_id), str(chat_request.session_id) if chat_request.session_id else None, profile, str(chunk[1]))
            yield {"type": "intake_complete", "profile": chunk[0].model_dump() if hasattr(chunk[0], "model_dump") else chunk[0], "transcript": chunk[1]}
        elif isinstance(chunk, dict):
            yield chunk
        else:
            yield {"type": "message", "content": chunk}
