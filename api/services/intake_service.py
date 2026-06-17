import uuid
from typing import AsyncIterable

from api.shared import ChatRequest
from agents.intake import run_intake_cli

from db.models import IntakeSession
from db.schemas import IntakeProfile
from db.repositories import IntakeRepo, SessionRepo
from db.db import unit_of_work

async def stream_intake_chat(chat_request: ChatRequest, user_id: str) -> AsyncIterable[dict]:
    
    intake_repo = IntakeRepo(user_id)
    chat_session_repo = SessionRepo()

    async with unit_of_work() as db:
        intake_session: IntakeSession = await intake_repo.get_or_create_session(db, chat_request.conversation_id)
        intake_session_id = intake_session.id
        await chat_session_repo.link_intake_session(db, user_id, chat_request.session_id, intake_session_id)
        
    
    async for chunk in run_intake_cli(chat_request.message, intake_session_id, user_id):
        if isinstance(chunk, tuple) and len(chunk) == 2 and isinstance(chunk[0], IntakeProfile):
            async with unit_of_work() as db:
                await intake_repo.update_session(db, intake_session_id, profile=chunk[0], transcript=chunk[1])
                await intake_repo.complete_session(db, intake_session_id)
            yield {"type": "intake_complete", "profile": chunk[0].model_dump() if hasattr(chunk[0], "model_dump") else chunk[0], "transcript": chunk[1]}
        elif isinstance(chunk, dict):
            yield chunk
        else:
            yield {"type": "message", "content": chunk}