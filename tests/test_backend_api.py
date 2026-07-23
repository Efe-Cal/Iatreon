import importlib
import hashlib
import sqlite3
import sys
from datetime import datetime, timezone

import jwt
from fastapi import HTTPException
from fastapi.testclient import TestClient


def load_backend(monkeypatch, tmp_path):
    monkeypatch.setenv("BACKEND_API_DB_URL", f"sqlite+aiosqlite:///{tmp_path / 'backend.sqlite3'}")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("HCAI_API_KEY", "hcai-upstream-key")
    for name in list(sys.modules):
        if name.startswith("backend_api."):
            del sys.modules[name]
    main = importlib.import_module("backend_api.main")
    importlib.import_module("backend_api.auth").PBKDF2_ITERATIONS = 1
    return main


def register(client, username="alice", password="password123"):
    return register_pair(client, username, password)["access_token"]


def register_pair(client, username="alice", password="password123"):
    response = client.post("/auth/register", json={"username": username, "password": password})
    assert response.status_code == 201
    return response.json()


def test_auth_lifecycle_failures_and_route_protection(monkeypatch, tmp_path):
    main = load_backend(monkeypatch, tmp_path)
    with TestClient(main.app) as client:
        token = register(client)
        duplicate = client.post("/auth/register", json={"username": "alice", "password": "password123"})
        login = client.post("/auth/token", json={"username": "alice", "password": "password123"})
        bad = client.post("/auth/token", json={"username": "alice", "password": "wrong-password"})
        unknown = client.post("/auth/token", json={"username": "nobody", "password": "wrong-password"})
        me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert client.get("/auth/me", headers={"Authorization": "Bearer malformed"}).status_code == 401
        assert client.post("/v1/chat/completions", json={}).status_code == 401
        assert client.post("/api/v1/pdf/jobs", json={"pdf_url": "https://example.com/a.pdf"}).status_code == 401

        monkeypatch.setenv("ACCESS_TOKEN_TTL_SECONDS", "-1")
        expired = client.post("/auth/token", json={"username": "alice", "password": "password123"}).json()["access_token"]
        assert client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401

        legacy = jwt.encode(
            {"sub": me.json()["id"], "exp": datetime.now(timezone.utc).timestamp() + 60},
            "test-secret",
            algorithm="HS256",
        )
        assert client.get("/auth/me", headers={"Authorization": f"Bearer {legacy}"}).status_code == 401

        with sqlite3.connect(tmp_path / "backend.sqlite3") as db:
            db.execute("delete from users where id = ?", (me.json()["id"],))
            db.commit()
        assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401

    assert duplicate.status_code == 409
    assert login.status_code == 200
    assert bad.status_code == unknown.status_code == 401
    assert bad.json() == unknown.json()
    assert me.json()["username"] == "alice"


def test_refresh_tokens_rotate_roll_and_reject_replay(monkeypatch, tmp_path):
    main = load_backend(monkeypatch, tmp_path)
    with TestClient(main.app) as client:
        pair = register_pair(client)
        access_payload = jwt.decode(pair["access_token"], "test-secret", algorithms=["HS256"])
        assert access_payload["typ"] == "access"
        assert 6.9 * 24 * 60 * 60 < access_payload["exp"] - access_payload["iat"] <= 7 * 24 * 60 * 60

        first = client.post("/auth/refresh", json={"refresh_token": pair["refresh_token"]})
        assert first.status_code == 200
        replacement = first.json()
        assert replacement["access_token"] != pair["access_token"]
        assert replacement["refresh_token"] != pair["refresh_token"]

        replay = client.post("/auth/refresh", json={"refresh_token": pair["refresh_token"]})
        assert replay.status_code == 401
        assert client.post("/auth/refresh", json={"refresh_token": replacement["refresh_token"]}).status_code == 401
        assert client.post("/auth/refresh", json={"refresh_token": "malformed"}).status_code == 401

    with sqlite3.connect(tmp_path / "backend.sqlite3") as db:
        rows = db.execute("select token_hash, expires_at from refresh_tokens").fetchall()
    assert pair["refresh_token"] not in repr(rows)
    assert hashlib.sha256(pair["refresh_token"].encode()).hexdigest() in {row[0] for row in rows}
    expires = datetime.fromisoformat(rows[1][1])
    now = datetime.now(timezone.utc)
    if expires.tzinfo is None:
        now = now.replace(tzinfo=None)
    remaining = (expires - now).total_seconds()
    assert 29.9 * 24 * 60 * 60 < remaining <= 30 * 24 * 60 * 60


def test_expired_refresh_token_requires_login(monkeypatch, tmp_path):
    main = load_backend(monkeypatch, tmp_path)
    with TestClient(main.app) as client:
        monkeypatch.setenv("REFRESH_TOKEN_TTL_SECONDS", "-1")
        pair = register_pair(client)
        response = client.post("/auth/refresh", json={"refresh_token": pair["refresh_token"]})
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid refresh token"}


def test_hcai_streams_query_headers_and_body_without_storage(monkeypatch, tmp_path):
    main = load_backend(monkeypatch, tmp_path)
    hcai = importlib.import_module("backend_api.hcai")
    calls = []

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json", "content-length": "999", "connection": "close"}
        async def aiter_bytes(self):
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

    monkeypatch.setattr(hcai.httpx, "AsyncClient", FakeAsyncClient)
    with TestClient(main.app) as client:
        token = register(client)
        response = client.post(
            "/v1/chat/completions?trace=1",
            json={"private": "secret-medical"},
            headers={"Authorization": f"Bearer {token}", "Accept-Encoding": "zstd", "X-Test": "kept"},
        )

    assert response.content == b'{"ok":true}'
    assert calls[0]["url"] == "https://ai.hackclub.com/proxy/v1/chat/completions"
    assert calls[0]["params"] == [("trace", "1")]
    assert calls[0]["headers"]["Authorization"] == "Bearer hcai-upstream-key"
    assert calls[0]["headers"]["accept-encoding"] == "identity"
    assert calls[0]["headers"]["x-test"] == "kept"
    assert calls[0]["stream"] is True
    assert b"secret-medical" in calls[0]["body"]
    with sqlite3.connect(tmp_path / "backend.sqlite3") as db:
        rows = db.execute("select username, password_hash, password_salt from users").fetchall()
    assert "secret-medical" not in repr(rows)


def test_pdf_ownership_status_expiry_and_leak_prevention(monkeypatch, tmp_path):
    main = load_backend(monkeypatch, tmp_path)
    pdf = importlib.import_module("backend_api.pdf")
    queued_ids = iter(["job-a", "job-b"])

    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code, self.payload = status_code, payload
        def json(self):
            return self.payload

    async def request(method, path, **kwargs):
        if method == "POST":
            return FakeResponse(202, {"job_id": next(queued_ids)})
        if path.endswith("job-a"):
            return FakeResponse(200, {"status": "started", "result": "C:/secret.pdf", "error": "traceback"})
        return FakeResponse(410, {})

    monkeypatch.setattr(pdf, "_worker_request", request)
    with TestClient(main.app) as client:
        alice, bob = register(client, "alice"), register(client, "bob")
        ah, bh = {"Authorization": f"Bearer {alice}"}, {"Authorization": f"Bearer {bob}"}
        created = client.post("/api/v1/pdf/jobs", json={"pdf_url": "https://example.com/a.pdf"}, headers=ah)
        client.post("/api/v1/pdf/jobs", json={"pdf_url": "https://example.com/b.pdf"}, headers=bh)
        response = client.get("/api/v1/pdf/jobs/job-a", headers=ah)
        hidden = client.get("/api/v1/pdf/jobs/job-a", headers=bh)
        missing = client.get("/api/v1/pdf/jobs/missing", headers=ah)
        expired = client.get("/api/v1/pdf/jobs/job-b", headers=bh)

    assert created.status_code == 202
    assert response.json() == {"job_id": "job-a", "status": "in-progress"}
    assert "secret" not in response.text and "traceback" not in response.text
    assert hidden.status_code == missing.status_code == 404
    assert expired.status_code == 410


def test_pdf_content_streaming_conflicts_and_unavailable_service(monkeypatch, tmp_path):
    main = load_backend(monkeypatch, tmp_path)
    pdf = importlib.import_module("backend_api.pdf")
    worker_status = "finished"

    class WorkerResponse:
        status_code = 202
        def json(self):
            return {"job_id": "job-stream"} if self.status_code == 202 else {"status": worker_status}

    async def worker_request(method, path, **kwargs):
        response = WorkerResponse()
        if method == "GET":
            response.status_code = 200
        return response

    class StreamResponse:
        status_code = 200
        async def aiter_raw(self):
            yield b"%PDF streamed"
        async def aclose(self):
            pass

    class AsyncClient:
        def __init__(self, *args, **kwargs):
            pass
        def build_request(self, method, url):
            return (method, url)
        async def send(self, request, stream=False):
            assert request[1].endswith("/download/job-stream") and stream
            return StreamResponse()
        async def aclose(self):
            pass

    monkeypatch.setattr(pdf, "_worker_request", worker_request)
    monkeypatch.setattr(pdf.httpx, "AsyncClient", AsyncClient)
    with TestClient(main.app) as client:
        headers = {"Authorization": f"Bearer {register(client)}"}
        client.post("/api/v1/pdf/jobs", json={"pdf_url": "https://example.com/a.pdf"}, headers=headers)
        content = client.get("/api/v1/pdf/jobs/job-stream/content", headers=headers)
        worker_status = "failed"
        conflict = client.get("/api/v1/pdf/jobs/job-stream/content", headers=headers)

        async def unavailable(*args, **kwargs):
            raise HTTPException(status_code=503, detail="PDF service unavailable")

        monkeypatch.setattr(pdf, "_worker_request", unavailable)
        unavailable_response = client.get("/api/v1/pdf/jobs/job-stream", headers=headers)

    assert content.status_code == 200 and content.content == b"%PDF streamed"
    assert conflict.status_code == 409
    assert unavailable_response.status_code == 503


def test_backup_upload_completion_and_download(monkeypatch, tmp_path):
    main = load_backend(monkeypatch, tmp_path)
    backup = importlib.import_module("backend_api.backup")
    calls = []

    class R2Client:
        def generate_presigned_url(self, ClientMethod, Params, ExpiresIn):
            calls.append((ClientMethod, Params, ExpiresIn))
            return f"https://r2.test/{ClientMethod}"

    monkeypatch.setattr(backup, "create_r2_client", R2Client)
    monkeypatch.setenv("R2_BUCKET_NAME", "backups")

    with TestClient(main.app) as client:
        headers = {"Authorization": f"Bearer {register(client)}"}
        upload = client.post("/backup/upload", headers=headers)
        backup_id = upload.json()["backup_id"]
        pending = client.get(f"/backup/download/{backup_id}", headers=headers)
        invalid = client.post(
            f"/backup/upload/{backup_id}/complete",
            json={"checksum": "invalid"},
            headers=headers,
        )
        complete = client.post(
            f"/backup/upload/{backup_id}/complete",
            json={"checksum": "a" * 64},
            headers=headers,
        )
        download = client.get(f"/backup/download/{backup_id}", headers=headers)
        listed = client.get("/backup/list", headers=headers)

    assert (
        upload.status_code
        == complete.status_code
        == download.status_code
        == listed.status_code
        == 200
    )
    assert pending.status_code == 409
    assert invalid.status_code == 422
    assert download.json()["checksum"] == "a" * 64
    assert listed.json() == {"backups": [{"id": backup_id, "checksum": "a" * 64}]}
    assert [call[0] for call in calls] == ["put_object", "get_object"]
    assert all(call[1]["Bucket"] == "backups" for call in calls)
