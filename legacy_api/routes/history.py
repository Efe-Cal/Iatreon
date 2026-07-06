from fastapi import APIRouter, Request

from legacy_api.shared import clear_encryption_context, get_user_id_or_400, require_encryption_context
from db.db import read_only_session
from db.repositories import SessionRepo

router = APIRouter()


@router.get('/history')
async def history(request: Request):
    user_id = get_user_id_or_400(request)
    token = require_encryption_context(request)
    try:
        async with read_only_session() as db:
            return {"sessions": await SessionRepo().list_history(db, user_id)}
    finally:
        clear_encryption_context(token)
