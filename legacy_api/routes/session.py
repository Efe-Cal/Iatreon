from uuid import UUID

from fastapi import APIRouter, Request

from legacy_api.shared import clear_encryption_context, require_encryption_context
from db.db import unit_of_work
from db.repositories import SessionRepo

router = APIRouter()


@router.get('/create-session')
async def create_session(user_id: UUID, request: Request):
    token = require_encryption_context(request)
    try:
        async with unit_of_work() as db:
            session_repo = SessionRepo()
            session = await session_repo.create_session(db, user_id)
            return {'session_id': session.id}
    finally:
        clear_encryption_context(token)
