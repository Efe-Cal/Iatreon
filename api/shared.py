from fastapi import Request, HTTPException
from pydantic import BaseModel

class ChatRequest(BaseModel):
    message: str
    conversation_id: str

# TODO: fix this
def get_user_id_or_400(request: Request) -> str:
    return "12d6bef53a914ffc804417758ad8e4d2"
    user_id = request.headers.get("X-User-ID", None)
    if not user_id:
        raise HTTPException(status_code=400, detail="X-User-ID header missing")
    return user_id