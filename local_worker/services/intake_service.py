import uuid
from typing import AsyncIterable

from models import ChatRequest
from agents.intake import run_intake_cli
from local_worker import store

from db.schemas import IntakeProfile

async def stream_intake_chat(chat_request: ChatRequest) -> AsyncIterable[dict]:
    user_id = str(chat_request.user_id)

    if not chat_request.conversation_id:
        chat_request.conversation_id = uuid.uuid4()

    intake_session_id = chat_request.conversation_id
    store.link_intake_session(str(chat_request.session_id) if chat_request.session_id else None, str(intake_session_id))
    
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
