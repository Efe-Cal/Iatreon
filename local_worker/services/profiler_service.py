from uuid import UUID

from agents.profiler import update_user_profile_with_chat_session
from db.schemas import ChatSessionData
from local_worker import store
from local_worker.errors import NotFoundError


async def update_profile_from_chat_session(user_id: UUID | str, chat_session_id: UUID | str) -> str:
    user_id = str(user_id)
    chat_session = store.get_chat_session_data(user_id, str(chat_session_id))
    if chat_session is None:
        raise NotFoundError("Chat session not found.")

    profile = store.get_profile(user_id)
    if not profile:
        raise NotFoundError("User profile not found.")

    medical_summary = await update_user_profile_with_chat_session(
        ChatSessionData.model_validate(chat_session),
        profile.get("medical_summary") or "",
    )
    if not isinstance(medical_summary, str) or not medical_summary.strip():
        raise RuntimeError("Profiler did not return a medical summary.")

    store.update_profile_medical_summary(user_id, medical_summary)
    return medical_summary
