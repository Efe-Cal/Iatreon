from agents.intake import run_intake_cli
from api.shared import ChatRequest
from db.models import IntakeSession
from db.schemas import IntakeProfile
from db.repositories import IntakeRepo
from db.db import SessionLocal

from typing import AsyncIterable



async def stream_intake_chat(chat_request: ChatRequest, user_id: str) -> AsyncIterable:
    async with SessionLocal() as session:
        intake_repo = IntakeRepo(session, user_id)
        intake_session: IntakeSession = await intake_repo.create_session()
        async for chunk in run_intake_cli(chat_request.message, chat_request.conversation_id):

            if isinstance(chunk, tuple) and len(chunk) == 2 and isinstance(chunk[0], IntakeProfile):
                await intake_repo.update_session(intake_session.id, profile=chunk[0], transcript=chunk[1])
                await intake_repo.complete_session(intake_session.id)
                yield {"type": "intake_complete", "profile": chunk[0], "transcript": chunk[1]}
            else:
                yield {"type": "message", "content": chunk}