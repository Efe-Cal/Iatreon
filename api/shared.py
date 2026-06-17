from uuid import UUID

from fastapi import Request, HTTPException
from pydantic import BaseModel

class ChatRequest(BaseModel):
    message: str
    conversation_id: UUID | None
    session_id: UUID | None

def get_user_id_or_400(request: Request) -> str:
    user_id = request.headers.get("X-User-ID", None)
    if not user_id:
        raise HTTPException(status_code=400, detail="X-User-ID header missing")
    return user_id