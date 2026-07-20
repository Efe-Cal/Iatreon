import asyncio
from uuid import UUID

from agents.profiler import update_user_profile_with_chat_session
from db.schemas import ChatSessionData
from local_worker import store
from local_worker.errors import NotFoundError
from local_worker.provider_config import (
    ensure_backend_session,
    reset_current_user_id,
    set_current_user_id,
)


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


async def drain_profile_update_jobs() -> None:
    while True:
        job = store.claim_profile_update_job()
        if job is None:
            delay = store.next_profile_update_delay()
            if delay is None:
                return
            await asyncio.sleep(min(delay, 60))
            continue

        token = set_current_user_id(job["user_id"])
        try:
            provider = store.get_provider_setup(job["user_id"]).get("llm_provider") or "Iatreon AI"
            if provider == "Iatreon AI":
                await ensure_backend_session(job["user_id"])
            await update_profile_from_chat_session(job["user_id"], job["chat_session_id"])
        except Exception as exc:
            store.fail_profile_update_job(job["chat_session_id"], job["revision"], str(exc))
        else:
            store.complete_profile_update_job(job["chat_session_id"], job["revision"])
        finally:
            reset_current_user_id(token)
