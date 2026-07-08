import importlib
import sqlite3

from fastapi.testclient import TestClient


def load_proxy(monkeypatch, tmp_path):
    monkeypatch.setenv("HCAI_PROXY_DB_URL", f"sqlite:///{tmp_path / 'proxy.sqlite3'}")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("HCAI_API_KEY", "hcai-upstream-key")

    import hcai_proxy.main as proxy

    proxy = importlib.reload(proxy)
    proxy.PBKDF2_ITERATIONS = 1
    return proxy


def get_token(client: TestClient, username: str = "alice", password: str = "password123") -> str:
    response = client.post("/auth/token", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


def test_auth_creates_user_logs_in_existing_user_and_rejects_bad_password(monkeypatch, tmp_path):
    proxy = load_proxy(monkeypatch, tmp_path)

    with TestClient(proxy.app) as client:
        first = client.post("/auth/token", json={"username": "alice", "password": "password123"})
        second = client.post("/auth/token", json={"username": "alice", "password": "password123"})
        bad = client.post("/auth/token", json={"username": "alice", "password": "wrong-password"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["token_type"] == "bearer"
    assert bad.status_code == 401


def test_proxy_requires_valid_bearer_token(monkeypatch, tmp_path):
    proxy = load_proxy(monkeypatch, tmp_path)

    with TestClient(proxy.app) as client:
        assert client.post("/v1/chat/completions", json={"input": "hi"}).status_code == 401
        assert client.post(
            "/v1/chat/completions",
            json={"input": "hi"},
            headers={"Authorization": "Bearer not-a-real-token"},
        ).status_code == 401


def test_proxy_forwards_llm_and_exa_with_upstream_key(monkeypatch, tmp_path):
    proxy = load_proxy(monkeypatch, tmp_path)
    calls = []

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json", "content-length": "999"}

        async def aiter_raw(self):
            yield b'{"ok":true}'

        async def aclose(self):
            pass

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        def build_request(self, method, url, params, headers, content):
            return {"method": method, "url": url, "params": params, "headers": headers, "content": content}

        async def send(self, request, stream=False):
            body = b""
            async for chunk in request["content"]:
                body += chunk
            calls.append({**request, "body": body, "stream": stream})
            return FakeResponse()

        async def aclose(self):
            pass

    monkeypatch.setattr(proxy.httpx, "AsyncClient", FakeAsyncClient)

    with TestClient(proxy.app) as client:
        token = get_token(client)
        llm = client.post(
            "/v1/chat/completions?trace=1",
            json={"messages": [{"role": "user", "content": "secret-medical"}]},
            headers={"Authorization": f"Bearer {token}", "X-Test": "kept"},
        )
        exa = client.post(
            "/v1/exa/search",
            json={"query": "migraine"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert llm.status_code == 200
    assert exa.status_code == 200
    assert calls[0]["url"] == "https://ai.hackclub.com/proxy/v1/chat/completions"
    assert calls[0]["params"] == [("trace", "1")]
    assert calls[0]["headers"]["Authorization"] == "Bearer hcai-upstream-key"
    assert calls[0]["headers"]["x-test"] == "kept"
    assert b"secret-medical" in calls[0]["body"]
    assert calls[1]["url"] == "https://ai.hackclub.com/proxy/v1/exa/search"
    assert calls[0]["stream"] is True


def test_proxy_does_not_store_proxied_request_body(monkeypatch, tmp_path):
    proxy = load_proxy(monkeypatch, tmp_path)
    db_path = tmp_path / "proxy.sqlite3"

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/plain"}

        async def aiter_raw(self):
            yield b"ok"

        async def aclose(self):
            pass

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        def build_request(self, method, url, params, headers, content):
            return {"content": content}

        async def send(self, request, stream=False):
            async for _ in request["content"]:
                pass
            return FakeResponse()

        async def aclose(self):
            pass

    monkeypatch.setattr(proxy.httpx, "AsyncClient", FakeAsyncClient)

    with TestClient(proxy.app) as client:
        token = get_token(client)
        response = client.post(
            "/v1/chat/completions",
            json={"private": "secret-medical"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    with sqlite3.connect(db_path) as db:
        rows = db.execute("select username, password_hash, password_salt from hcai_proxy_users").fetchall()
    assert rows
    assert "secret-medical" not in repr(rows)
