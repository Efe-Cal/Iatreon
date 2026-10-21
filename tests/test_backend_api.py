import asyncio
import importlib
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone

import jwt
from fastapi import HTTPException
from fastapi.testclient import TestClient


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}

    async def ping(self):
        return True

    async def incr(self, key):
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def decr(self, key):
        self.values[key] = self.values.get(key, 0) - 1
        return self.values[key]

    async def expire(self, key, seconds):
        self.ttls[key] = seconds

    async def ttl(self, key):
        return self.ttls.get(key, -1)

    async def delete(self, key):
        self.values.pop(key, None)
        self.ttls.pop(key, None)

    async def eval(self, script, numkeys, key):
        assert numkeys == 1
        # Redis executes the lease-release script without interleaving commands.
        self.values[key] = self.values.get(key, 0) - 1
        if self.values[key] <= 0:
            self.values.pop(key)
            self.ttls.pop(key, None)
            return 1
        return 0


def test_active_lease_release_preserves_concurrent_acquisition(monkeypatch, tmp_path):
    load_backend(monkeypatch, tmp_path)
    limits = importlib.import_module("backend_api.limits")
    replacement = None

    class RacingRedis(FakeRedis):
        async def decr(self, key):
            nonlocal replacement
            count = await super().decr(key)
            if count == 0:
                replacement = await limits.acquire_active_limit("test", "user", 1)
            return count

    redis = RacingRedis()
    monkeypatch.setattr(limits, "_redis", redis)

    async def release_and_reacquire():
        nonlocal replacement
        first = await limits.acquire_active_limit("test", "user", 1)
        await first.release()
        if replacement is None:
            replacement = await limits.acquire_active_limit("test", "user", 1)
        await first.release()  # Releasing twice must not remove the replacement.
        try:
            await limits.acquire_active_limit("test", "user", 1)
        except HTTPException as exc:
            assert exc.status_code == 429
        else:
            raise AssertionError("active limit admitted a second request")

    asyncio.run(release_and_reacquire())


def load_backend(monkeypatch, tmp_path):
    monkeypatch.setenv("BACKEND_API_DB_URL", f"sqlite+aiosqlite:///{tmp_path / 'backend.sqlite3'}")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("HCAI_API_KEY", "hcai-upstream-key")
    for name in list(sys.modules):
        if name.startswith("backend_api."):
            del sys.modules[name]
    main = importlib.import_module("backend_api.main")
    importlib.import_module("backend_api.limits")._redis = FakeRedis()
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
            calls.append({**request, "body": request["content"], "stream": stream})
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
    assert isinstance(calls[0]["body"], bytes)
    assert json.loads(calls[0]["body"]) == {"private": "secret-medical", "max_tokens": 2000}
    with sqlite3.connect(tmp_path / "backend.sqlite3") as db:
        rows = db.execute("select username, password_hash, password_salt from users").fetchall()
    assert "secret-medical" not in repr(rows)


def test_hcai_rejects_non_object_and_oversized_bodies(monkeypatch, tmp_path):
    main = load_backend(monkeypatch, tmp_path)
    with TestClient(main.app) as client:
        headers = {"Authorization": f"Bearer {register(client)}"}
        non_object = client.post(
            "/v1/chat/completions",
            content=b"[]",
            headers={**headers, "Content-Type": "application/json"},
        )
        oversized = client.post(
            "/v1/chat/completions",
            content=b"x" * (2 * 1024 * 1024 + 1),
            headers={**headers, "Content-Type": "application/octet-stream"},
        )

    assert non_object.status_code == 422
    assert oversized.status_code == 413


def test_register_rate_limit_and_redis_failure_are_fail_closed(monkeypatch, tmp_path):
    main = load_backend(monkeypatch, tmp_path)
    limits = importlib.import_module("backend_api.limits")
    with TestClient(main.app) as client:
        for index in range(limits.REGISTER_LIMIT.count):
            assert client.post(
                "/auth/register",
                json={"username": f"user-{index}", "password": "password123"},
            ).status_code == 201
        limited = client.post(
            "/auth/register",
            json={"username": "limited", "password": "password123"},
        )
        limits._redis = None
        monkeypatch.setattr(limits, "redis_asyncio", None)
        unavailable = client.post(
            "/auth/register",
            json={"username": "unavailable", "password": "password123"},
        )

    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) > 0
    assert unavailable.status_code == 503


def test_login_limits_normalized_username_and_health_checks_redis(monkeypatch, tmp_path):
    main = load_backend(monkeypatch, tmp_path)
    limits = importlib.import_module("backend_api.limits")
    auth = importlib.import_module("backend_api.auth")
    monkeypatch.setattr(auth, "LOGIN_IP_LIMIT", limits.RateLimit(100, 60))
    with TestClient(main.app) as client:
        assert client.get("/health").json() == {"status": "ok", "redis": "ok"}
        for username in (" Missing ", "missing", "MISSING", "missing", "missing"):
            assert client.post(
                "/auth/token",
                json={"username": username, "password": "password123"},
            ).status_code == 401
        limited = client.post(
            "/auth/token",
            json={"username": "missing", "password": "password123"},
        )

    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) > 0


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


def test_backup_stream_upload_and_download(monkeypatch, tmp_path):
    main = load_backend(monkeypatch, tmp_path)
    backup = importlib.import_module("backend_api.backup")
    calls = []

    class R2Client:
        def upload_file(self, filename, bucket, key, ExtraArgs):
            with open(filename, "rb") as source:
                calls.append(("upload_file", bucket, key, ExtraArgs, source.read()))

        def delete_object(self, Bucket, Key):
            calls.append(("delete_object", Bucket, Key))

        def generate_presigned_url(self, ClientMethod, Params, ExpiresIn):
            calls.append((ClientMethod, Params, ExpiresIn))
            return f"https://r2.test/{ClientMethod}"

    monkeypatch.setattr(backup, "create_r2_client", R2Client)
    monkeypatch.setenv("R2_BUCKET_NAME", "backups")

    with TestClient(main.app) as client:
        headers = {"Authorization": f"Bearer {register(client)}"}
        body = b"encrypted backup"
        checksum = hashlib.sha256(body).hexdigest()
        upload = client.put(
            "/backup/upload",
            content=body,
            headers={
                **headers,
                "Content-Type": "application/octet-stream",
                "Content-Length": str(len(body)),
                "X-Backup-Checksum": checksum,
            },
        )
        backup_id = upload.json()["backup_id"]
        invalid = client.put(
            "/backup/upload",
            content=body,
            headers={
                **headers,
                "Content-Type": "application/octet-stream",
                "Content-Length": str(len(body)),
                "X-Backup-Checksum": "invalid",
            },
        )
        download = client.get(f"/backup/download/{backup_id}", headers=headers)
        listed = client.get("/backup/list", headers=headers)

    assert (
        upload.status_code
        == download.status_code
        == listed.status_code
        == 200
    )
    assert invalid.status_code == 422
    assert upload.json() == {"status": "success", "backup_id": backup_id, "checksum": checksum}
    assert download.json()["checksum"] == checksum
    listed_backup = listed.json()["backups"][0]
    assert listed_backup["id"] == backup_id
    assert listed_backup["checksum"] == checksum
    assert datetime.fromisoformat(listed_backup["created_at"])
    assert calls[0][0] == "upload_file"
    assert calls[0][1] == "backups"
    assert calls[0][2].endswith(f"/{backup_id}.db")
    assert calls[0][3] == {"ContentType": "application/octet-stream"}
    assert calls[0][4] == body
    assert calls[1][0] == "get_object"
    assert calls[1][1]["Bucket"] == "backups"


def test_backup_retains_only_latest_five(monkeypatch, tmp_path):
    main = load_backend(monkeypatch, tmp_path)
    backup = importlib.import_module("backend_api.backup")
    limits = importlib.import_module("backend_api.limits")
    deleted = []

    class R2Client:
        def upload_file(self, filename, bucket, key, ExtraArgs):
            pass

        def delete_object(self, Bucket, Key):
            deleted.append((Bucket, Key))

    monkeypatch.setattr(backup, "create_r2_client", R2Client)
    monkeypatch.setenv("R2_BUCKET_NAME", "backups")
    monkeypatch.setattr(backup, "BACKUP_LIMIT", limits.RateLimit(10, 3600))

    with TestClient(main.app) as client:
        headers = {"Authorization": f"Bearer {register(client)}"}
        for index in range(6):
            body = f"backup-{index}".encode()
            response = client.put(
                "/backup/upload",
                content=body,
                headers={
                    **headers,
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(len(body)),
                    "X-Backup-Checksum": hashlib.sha256(body).hexdigest(),
                },
            )
            assert response.status_code == 200
        listed = client.get("/backup/list", headers=headers)

    assert len(listed.json()["backups"]) == 5
    assert len(deleted) == 1
