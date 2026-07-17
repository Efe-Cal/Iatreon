import base64
import asyncio
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import text

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

    store.update_backend_session(user_id, "alice", "jwt-test", "refresh-test")
    assert store.get_backend_session(user_id) == {
        "username": "alice",
        "access_token": "jwt-test",
        "refresh_token": "refresh-test",
    }
    with store._engine.connect() as db:
        tables = {row[0] for row in db.execute(text("select name from sqlite_master where type='table'"))}
        columns = {row[1] for row in db.execute(text("pragma table_info(backend_session)"))}
    assert "backend_refresh_session" not in tables
    assert columns == {"user_id", "username", "access_token", "refresh_token"}

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


def test_settings_route_returns_profile_and_provider_setup(initialized_store):
    from local_worker import worker

    user_id = uuid.uuid4()
    profile = {
        "user_id": str(user_id),
        "demographics": {"age": "35", "gender": "Female"},
        "allergies": ["penicillin"],
    }
    providers = {
        "user_id": str(user_id),
        "llm_provider": "OpenRouter",
        "llm_api_key": "sk-test",
        "llm_base_url": "https://openrouter.ai/api/v1",
        "search_provider": "Exa",
        "search_api_key": "exa-test",
        "search_base_url": "",
    }
    store.update_profile(profile)
    store.update_provider_setup(providers)

    result = asyncio.run(worker.get_settings(worker.SettingsRequest(user_id=user_id)))

    assert result == {"profile": profile, "provider_setup": providers}


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
    store.update_backend_session(user_id, "alice", "jwt-one-place", "refresh-one-place")
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


def test_expired_access_token_refreshes_and_rotates_local_pair(initialized_store, monkeypatch):
    monkeypatch.setenv("IATREON_LOCAL_WORKER", "1")
    user_id = str(uuid.uuid4())
    store.update_backend_session(user_id, "alice", "expired", "refresh-old")

    from local_worker import provider_config

    class Response:
        status_code = 200

        def json(self):
            return {"access_token": "access-new", "refresh_token": "refresh-new"}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, json):
            assert url.endswith("/auth/refresh")
            assert json == {"refresh_token": "refresh-old"}
            return Response()

    monkeypatch.setattr(provider_config.httpx, "AsyncClient", lambda **kwargs: Client())
    session = asyncio.run(provider_config.ensure_backend_session(user_id))
    assert session == {
        "username": "alice",
        "access_token": "access-new",
        "refresh_token": "refresh-new",
    }


def test_refresh_outage_does_not_become_reauthentication(initialized_store, monkeypatch):
    monkeypatch.setenv("IATREON_LOCAL_WORKER", "1")
    user_id = str(uuid.uuid4())
    store.update_backend_session(user_id, "alice", "expired", "refresh-old")

    from local_worker import provider_config

    class Response:
        status_code = 503

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, json):
            return Response()

    monkeypatch.setattr(provider_config.httpx, "AsyncClient", lambda **kwargs: Client())
    with pytest.raises(provider_config.BackendAuthUnavailable):
        asyncio.run(provider_config.ensure_backend_session(user_id))
    assert store.get_backend_session(user_id)["refresh_token"] == "refresh-old"


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


def test_backup_transfer_uses_configured_backend_and_private_auth(
    initialized_store, monkeypatch, tmp_path
):
    import httpx

    user_id = str(uuid.uuid4())
    store.update_backend_session(user_id, "alice", "jwt-test", "refresh-test")
    backup_path = tmp_path / "backup.db"
    backup_path.write_bytes(b"encrypted backup")
    checksum = store.calculate_sha256(backup_path)
    destination_path = tmp_path / "downloaded.db"
    calls = []

    class Response:
        def __init__(self, status_code=200, payload=None, content=b""):
            self.status_code = status_code
            self._payload = payload
            self.content = content
            self.text = ""

        def json(self):
            return self._payload

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, **kwargs):
            calls.append(("POST", url, kwargs))
            if url.endswith("/backup/upload"):
                return Response(payload={"upload_url": "https://r2.test/upload", "backup_id": "one"})
            return Response(payload={"status": "success"})

        async def put(self, url, **kwargs):
            calls.append(("PUT", url, {**kwargs, "body": kwargs["data"].read()}))
            return Response()

        async def get(self, url, **kwargs):
            calls.append(("GET", url, kwargs))
            if url.startswith("https://backend.test"):
                return Response(
                    payload={"download_url": "https://r2.test/download", "checksum": checksum}
                )
            return Response(content=b"encrypted backup")

    monkeypatch.setenv("IATREON_BACKEND_API_URL", "https://backend.test/")
    monkeypatch.setattr(httpx, "AsyncClient", Client)

    asyncio.run(store.upload_backup(backup_path, user_id, checksum))
    asyncio.run(store.download_backup("one", user_id, destination_path))

    assert calls[0][1] == "https://backend.test/backup/upload"
    assert calls[1][2]["headers"] == {"Content-Type": "application/octet-stream"}
    assert calls[1][2]["body"] == b"encrypted backup"
    assert calls[2][2]["json"] == {"checksum": checksum}
    assert calls[3][1] == "https://backend.test/backup/download/one"
    assert "headers" not in calls[4][2]
    assert destination_path.read_bytes() == b"encrypted backup"


def test_backup_route_converts_paths_and_refreshes_auth(monkeypatch, tmp_path):
    from local_worker import worker

    source_path = tmp_path / "source.db"
    backup_path = tmp_path / "backup.db"
    seen = {}

    async def create_encrypted_backup(source_path, backup_path, db_key):
        seen["create"] = (source_path, backup_path, db_key)
        return "a" * 64

    async def upload_backup(path, user_id, checksum):
        seen["upload"] = (path, user_id, checksum)

    monkeypatch.setattr(worker.store, "create_encrypted_backup", create_encrypted_backup)
    monkeypatch.setattr(worker.store, "upload_backup", upload_backup)
    request = worker.BackupRequest(
        user_id=uuid.uuid4(),
        source_path=str(source_path),
        backup_path=str(backup_path),
        db_key="key",
    )

    result = asyncio.run(worker.backup_data(request))

    assert result == {"status": "success"}
    assert seen["create"] == (source_path, backup_path, "key")
    assert seen["upload"][0] == backup_path
    assert "data/backup" in worker.BACKEND_AUTH_ROUTES
