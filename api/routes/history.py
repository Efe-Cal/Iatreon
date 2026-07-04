from fastapi import APIRouter, Depends, Request

from api.security import AuthContext, require_auth
from api.shared import clear_encryption_context, require_encryption_context
from db.db import read_only_session
from db.repositories import SessionRepo

router = APIRouter()


@router.get('/history')
async def history(request: Request, auth: AuthContext = Depends(require_auth)):
    user_id = str(auth.user_id)
    token = require_encryption_context(request)
    try:
        async with read_only_session() as db:
            return {"sessions": await SessionRepo().list_history(db, user_id)}
    finally:
        clear_encryption_context(token)
