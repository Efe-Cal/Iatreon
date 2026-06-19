import uuid
from typing import AsyncIterable

from api.shared import ChatRequest

from agents.doctor import DoctorAgent

from db.models import DoctorSession
from db.repositories import DoctorRepo, SessionRepo
from db.db import unit_of_work

async def stream_doctor_chat(chat_request: ChatRequest, user_id: str) -> AsyncIterable[dict]:
    
    doctor_repo = DoctorRepo(user_id)
    chat_session_repo = SessionRepo()

    if not chat_request.conversation_id:
        chat_request.conversation_id = uuid.uuid4()
        
    doctor_agent = DoctorAgent()
    
    async with unit_of_work() as db:
        doctor_session: DoctorSession = await doctor_repo.create_doctor_session(db, user_id, chat_request.session_id, chat_request.conversation_id)
        await chat_session_repo.link_session(db, user_id, chat_request.session_id, doctor_session)
    
    async for event in doctor_agent.run_doctor():
        yield event