import base64
import uuid
from unittest.mock import patch

import pytest

pytest.importorskip("sqlcipher3")

from local_worker import store


def _key(seed: bytes) -> str:
    return base64.b64encode(seed * 32).decode("ascii")


@pytest.fixture()
def initialized_store(tmp_path):
    store._reset_for_tests()
    db_path = tmp_path / "local.sqlite3"
    store.initialize(str(db_path), _key(b"a"))
    try:
        yield db_path
    finally:
        store._reset_for_tests()


def test_store_round_trips_worker_records(initialized_store):
    user_id = str(uuid.uuid4())
    session_id = store.create_session(user_id)

    profile = {
        "user_id": user_id,
        "demographics": {"age": "35"},
        "allergies": ["penicillin"],
        "medical_summary": "Headache for two days.",
    }
    store.update_profile(profile)
    assert store.has_profile(user_id)
    assert store.get_profile(user_id) == profile
    assert "penicillin" in store.profile_markdown(user_id)

    provider_setup = {
        "user_id": user_id,
        "llm_provider": "OpenRouter",
        "llm_api_key": "sk-test",
        "llm_base_url": "https://openrouter.ai/api/v1",
        "search_provider": "Exa",
        "search_api_key": "exa-test",
        "search_base_url": "",
    }
    store.update_provider_setup(provider_setup)
    assert store.has_provider_setup(user_id)
    assert store.get_provider_setup(user_id) == provider_setup

    store.update_backend_session(user_id, "alice", "jwt-test")
    assert store.get_backend_session(user_id) == {"username": "alice", "jwt": "jwt-test"}

    intake_id = str(uuid.uuid4())
    store.link_intake_session(session_id, intake_id)
    store.save_intake(user_id, intake_id, session_id, profile, "transcript")
    assert store.get_intake(intake_id)["profile"] == profile
    assert store.get_intake_by_chat_session(session_id)["id"] == intake_id

    research_id = str(uuid.uuid4())
    store.save_research(
        user_id,
        research_id,
        session_id,
        "standard",
        "research report",
        {1: {"text": "citation text"}},
    )
    latest = store.get_latest_research(user_id, session_id)
    assert latest["id"] == research_id
    assert store.get_citation_text(research_id, 1) == "citation text"

    diagnosis_id = str(uuid.uuid4())
    store.save_diagnosis(user_id, diagnosis_id, intake_id, session_id, {"primary_diagnosis": "Migraine"})

    history = store.list_history(user_id)
    assert history[0]["id"] == session_id
    assert [section["type"] for section in history[0]["sections"]] == ["intake", "research", "diagnosis"]


def test_local_provider_setup_drives_model_and_search_clients(initialized_store, monkeypatch):
    monkeypatch.setenv("IATREON_LOCAL_WORKER", "1")
    user_id = str(uuid.uuid4())
    store.update_provider_setup({
        "user_id": user_id,
        "llm_provider": "Groq",
        "llm_api_key": "groq-key",
        "llm_base_url": "",
        "search_provider": "Exa",
        "search_api_key": "exa-key",
        "search_base_url": "",
    })

    from agents import shared
    from context import websearch
    from local_worker.provider_config import reset_current_user_id, set_current_user_id

    token = set_current_user_id(user_id)
    try:
        with patch.object(shared, "ChatOpenAI") as chat:
            shared.get_model("intake")
            assert chat.call_args.kwargs["api_key"] == "groq-key"
            assert chat.call_args.kwargs["base_url"] == "https://api.groq.com/openai/v1"

        with patch.object(websearch, "Exa") as exa_cls:
            exa_cls.return_value.headers = {"x-api-key": "exa-key"}
            websearch.make_exa_client()
            assert exa_cls.call_args.kwargs == {"api_key": "exa-key"}
            assert exa_cls.return_value.headers["Authorization"] == "Bearer exa-key"
    finally:
        reset_current_user_id(token)


def test_iatreon_ai_defaults_use_proxy(monkeypatch):
    monkeypatch.delenv("IATREON_LOCAL_WORKER", raising=False)
    monkeypatch.delenv("AI_API_BASE_URL", raising=False)
    monkeypatch.delenv("EXA_BASE_URL", raising=False)

    from local_worker.provider_config import llm_config, search_config

    assert llm_config()["base_url"] == "https://iatreon.efecal.hackclub.app/v1"
    assert search_config()["base_url"] == "https://iatreon.efecal.hackclub.app/v1/exa"


def test_iatreon_clients_reuse_dedicated_backend_session(initialized_store, monkeypatch):
    monkeypatch.setenv("IATREON_LOCAL_WORKER", "1")
    user_id = str(uuid.uuid4())
    store.update_backend_session(user_id, "alice", "jwt-one-place")
    store.update_provider_setup({
        "user_id": user_id,
        "llm_provider": "Iatreon AI",
        "llm_api_key": "",
        "llm_base_url": "",
        "search_provider": "Iatreon AI",
        "search_api_key": "",
        "search_base_url": "",
    })
    from local_worker.provider_config import llm_config, reset_current_user_id, search_config, set_current_user_id

    context_token = set_current_user_id(user_id)
    try:
        assert llm_config()["api_key"] == "jwt-one-place"
        assert search_config()["api_key"] == "jwt-one-place"
    finally:
        reset_current_user_id(context_token)


def test_store_reopens_with_same_key(initialized_store):
    user_id = str(uuid.uuid4())
    session_id = store.create_session(user_id)

    store._reset_for_tests()
    store.initialize(str(initialized_store), _key(b"a"))

    assert store.list_history(user_id)[0]["id"] == session_id


def test_store_rejects_wrong_key(initialized_store):
    store.create_session(str(uuid.uuid4()))
    store._reset_for_tests()

    with pytest.raises(Exception):
        store.initialize(str(initialized_store), _key(b"b"))


def test_store_requires_init():
    store._reset_for_tests()
    with pytest.raises(RuntimeError, match="not initialized"):
        store.create_session(str(uuid.uuid4()))
