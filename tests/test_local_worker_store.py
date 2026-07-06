import base64
import uuid

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
