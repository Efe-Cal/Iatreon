from local_worker.store.backend_session import (
    BackendAuthRequired,
    BackendAuthUnavailable,
    backend_api_url,
    backend_session,
    ensure_backend_session,
    get_backend_session,
    has_backend_session,
    update_backend_session,
)

from local_worker.store.backups import (
    calculate_sha256,
    create_encrypted_backup,
    download_backup,
    upload_backup,
)
from local_worker.store.checkpointer import (
    close_checkpointer,
    get_checkpointer,
    initialize_checkpointer,
)


from local_worker.store.conversation_session import (
    create_session,
    get_chat_session_data,
    get_citation_text,
    get_intake,
    get_intake_by_chat_session,
    get_latest_research,
    get_profile,
    has_profile,
    link_doctor_session,
    link_intake_session,
    list_history,
    profile_markdown,
    save_diagnosis,
    save_intake,
    save_research,
    update_profile,
    update_profile_medical_summary,
)

from local_worker.store.database import _reset_for_tests, initialize
from local_worker.store.profile_jobs import (
    claim_profile_update_job,
    complete_profile_update_job,
    fail_profile_update_job,
    has_pending_profile_update_jobs,
    next_profile_update_delay,
    upsert_profile_update_job,
)


from local_worker.store.provider_setup import (
    get_provider_setup,
    has_provider_setup,
    update_provider_setup,
)

__all__ = [
    "BackendAuthRequired",
    "BackendAuthUnavailable",
    "backend_api_url",
    "backend_session",
    "calculate_sha256",
    "claim_profile_update_job",
    "close_checkpointer",
    "complete_profile_update_job",
    "create_encrypted_backup",
    "create_session",
    "download_backup",
    "ensure_backend_session",
    "fail_profile_update_job",
    "get_backend_session",
    "get_chat_session_data",
    "get_checkpointer",
    "get_citation_text",
    "get_intake",
    "get_intake_by_chat_session",
    "get_latest_research",
    "get_profile",
    "get_provider_setup",
    "has_backend_session",
    "has_pending_profile_update_jobs",
    "has_profile",
    "has_provider_setup",
    "initialize",
    "initialize_checkpointer",
    "link_doctor_session",
    "link_intake_session",
    "list_history",
    "next_profile_update_delay",
    "profile_markdown",
    "save_diagnosis",
    "save_intake",
    "save_research",
    "update_backend_session",
    "update_profile",
    "update_profile_medical_summary",
    "update_provider_setup",
    "upload_backup",
    "upsert_profile_update_job",
]



def __getattr__(name: str):
    # Backward compatibility for the existing storage test that inspects the live engine. Do not add new private internals to this facade.
    if name == "_engine":
        from local_worker.store import database

        return database._engine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
