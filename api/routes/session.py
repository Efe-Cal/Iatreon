from uuid import UUID

from fastapi import APIRouter

from db.db import unit_of_work
from db.repositories import SessionRepo

router = APIRouter()

@router.get("/create-session")
async def create_session(user_id: UUID):
    async with unit_of_work() as db:
        session_repo = SessionRepo()
        session = await session_repo.create_session(db, user_id)
        return {"session_id": session.id}
