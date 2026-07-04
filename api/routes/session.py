from fastapi import APIRouter, Depends, Request

from api.security import AuthContext, require_auth
from api.shared import clear_encryption_context, require_encryption_context
from db.db import unit_of_work
from db.repositories import SessionRepo

router = APIRouter()


@router.get('/create-session')
async def create_session(request: Request, auth: AuthContext = Depends(require_auth)):
    token = require_encryption_context(request)
    try:
        async with unit_of_work() as db:
            session_repo = SessionRepo()
            session = await session_repo.create_session(db, auth.user_id)
            return {'session_id': session.id}
    finally:
        clear_encryption_context(token)
