import contextvars
from typing import Any

_current_user_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("iatreon_user_id", default=None)
    

def set_current_user_id(user_id: Any):
    return _current_user_id.set(str(user_id) if user_id else None)


def reset_current_user_id(token) -> None:
    _current_user_id.reset(token)

def current_user_id() -> str | None:
    return _current_user_id.get()