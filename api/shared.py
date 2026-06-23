from uuid import UUID

from fastapi import HTTPException, Request
from pydantic import BaseModel

from db.crypto import reset_session_kek, set_session_kek


class ChatRequest(BaseModel):
    message: str
    conversation_id: UUID | None
    session_id: UUID | None


def get_user_id_or_400(request: Request) -> str:
    user_id = request.headers.get('X-User-ID', None)
    if not user_id:
        raise HTTPException(status_code=400, detail='X-User-ID header missing')
    return user_id


def require_encryption_context(request: Request):
    encoded_key = request.headers.get('X-Session-Key', None)
    if not encoded_key:
        raise HTTPException(status_code=400, detail='X-Session-Key header missing')
    try:
        return set_session_kek(encoded_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def clear_encryption_context(token) -> None:
    reset_session_kek(token)
