import base64
import hashlib
import hmac
import json
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse


UPSTREAM_BASE_URL = "https://ai.hackclub.com/proxy/v1"
JWT_ALG = "HS256"
PBKDF2_ITERATIONS = 210_000
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "hcai_proxy_users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    username: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    password_salt: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


def _database_url() -> str:
    return os.getenv("HCAI_PROXY_DB_URL", "sqlite:///./hcai_proxy.sqlite3")


def _engine_kwargs(database_url: str) -> dict:
    if database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {}


engine = create_engine(_database_url(), future=True, **_engine_kwargs(_database_url()))
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db() -> None:
    Base.metadata.create_all(engine)


def db_session():
    with SessionLocal() as db:
        yield db


class TokenRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=1024)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _json_b64(data: dict) -> str:
    return _b64url(json.dumps(data, separators=(",", ":"), default=str).encode("utf-8"))


def _jwt_secret() -> bytes:
    secret = os.getenv("JWT_SECRET", "")
    if not secret:
        raise RuntimeError("JWT_SECRET is required")
    return secret.encode("utf-8")


def _upstream_key() -> str:
    key = os.getenv("HCAI_API_KEY", "")
    if not key:
        raise RuntimeError("HCAI_API_KEY is required")
    return key


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt_bytes = _b64url_decode(salt) if salt else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, PBKDF2_ITERATIONS)
    return _b64url(digest), _b64url(salt_bytes)


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    got, _ = hash_password(password, salt)
    return hmac.compare_digest(got, password_hash)


def create_jwt(user: User) -> str:
    now = datetime.now(timezone.utc)
    ttl = int(os.getenv("JWT_TTL_SECONDS", str(30 * 24 * 60 * 60)))
    header = {"alg": JWT_ALG, "typ": "JWT"}
    payload = {
        "sub": user.id,
        "username": user.username,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
    }
    signing_input = f"{_json_b64(header)}.{_json_b64(payload)}"
    signature = hmac.new(_jwt_secret(), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url(signature)}"


def verify_jwt(token: str) -> dict:
    try:
        header_part, payload_part, signature_part = token.split(".")
        signing_input = f"{header_part}.{payload_part}"
        expected = hmac.new(_jwt_secret(), signing_input.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64url(expected), signature_part):
            raise ValueError("bad signature")
        header = json.loads(_b64url_decode(header_part))
        if header.get("alg") != JWT_ALG:
            raise ValueError("bad algorithm")
        payload = json.loads(_b64url_decode(payload_part))
        if int(payload.get("exp", 0)) < int(datetime.now(timezone.utc).timestamp()):
            raise ValueError("expired")
        return payload
    except Exception as exc:
        raise HTTPException(status_code=401, detail="invalid bearer token") from exc


def current_user_payload(authorization: Annotated[str | None, Header()] = None) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="bearer token required")
    return verify_jwt(authorization.removeprefix("Bearer ").strip())


def _filtered_request_headers(headers) -> dict[str, str]:
    blocked = HOP_BY_HOP_HEADERS | {"host", "authorization", "content-length"}
    return {key: value for key, value in headers.items() if key.lower() not in blocked}


def _filtered_response_headers(headers) -> dict[str, str]:
    blocked = HOP_BY_HOP_HEADERS | {"content-encoding", "content-length"}
    return {key: value for key, value in headers.items() if key.lower() not in blocked}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/auth/token", response_model=TokenResponse)
def token(payload: TokenRequest, db: Session = Depends(db_session)) -> TokenResponse:
    username = payload.username.strip()
    if not username:
        raise HTTPException(status_code=422, detail="username is required")

    user = db.scalars(select(User).where(User.username == username)).first()
    if user is None:
        password_hash, salt = hash_password(payload.password)
        user = User(username=username, password_hash=password_hash, password_salt=salt)
        db.add(user)
        db.commit()
        db.refresh(user)
    elif not verify_password(payload.password, user.password_hash, user.password_salt):
        raise HTTPException(status_code=401, detail="invalid username or password")

    return TokenResponse(access_token=create_jwt(user))


@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy(
    path: str,
    request: Request,
    _: dict = Depends(current_user_payload),
) -> StreamingResponse:
    try:
        upstream_key = _upstream_key()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    async def request_body():
        async for chunk in request.stream():
            yield chunk

    headers = _filtered_request_headers(request.headers)
    headers["Authorization"] = f"Bearer {upstream_key}"

    client = httpx.AsyncClient(timeout=None)
    upstream_request = client.build_request(
        request.method,
        f"{UPSTREAM_BASE_URL}/{path}",
        params=request.query_params.multi_items(),
        headers=headers,
        content=request_body(),
    )

    try:
        upstream_response = await client.send(upstream_request, stream=True)
    except Exception as exc:
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"Hack Club AI proxy failed: {exc}") from exc

    async def close_upstream() -> None:
        await upstream_response.aclose()
        await client.aclose()

    return StreamingResponse(
        upstream_response.aiter_raw(),
        status_code=upstream_response.status_code,
        headers=_filtered_response_headers(upstream_response.headers),
        background=BackgroundTask(close_upstream),
    )
