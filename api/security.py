import base64
import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException, Request, status

from db.db import read_only_session
from db.models import AuthSession


ACCESS_TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "15"))
REFRESH_TOKEN_DAYS = int(os.getenv("REFRESH_TOKEN_DAYS", "180"))
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-jwt-secret-change-me")
PASSWORD_ITERATIONS = 210_000


@dataclass(frozen=True)
class AuthContext:
    user_id: UUID
    session_id: UUID


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def is_expired(value: datetime) -> bool:
    if value.tzinfo is None:
        return value <= datetime.utcnow()
    return value <= utcnow()


def normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if not normalized or "@" not in normalized:
        raise ValueError("valid email is required")
    return normalized


def generate_session_key_salt() -> str:
    return _b64url(os.urandom(16))


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return "$".join(
        [
            "pbkdf2_sha256",
            str(PASSWORD_ITERATIONS),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        ]
    )


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        alg, iterations_text, salt_text, digest_text = password_hash.split("$", 3)
        if alg != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        salt = base64.b64decode(salt_text, validate=True)
        expected = base64.b64decode(digest_text, validate=True)
    except Exception:
        return False
    got = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(got, expected)


def create_access_token(user_id: UUID, session_id: UUID) -> tuple[str, datetime]:
    issued_at = utcnow()
    expires_at = issued_at + timedelta(minutes=ACCESS_TOKEN_MINUTES)
    payload = {
        "type": "access",
        "sub": str(user_id),
        "sid": str(session_id),
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": secrets.token_urlsafe(16),
    }
    return _encode_jwt(payload), expires_at


def decode_access_token(token: str) -> dict[str, Any]:
    payload = _decode_jwt(token)
    if payload.get("type") != "access":
        raise_auth_error("invalid token type")
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp <= int(utcnow().timestamp()):
        raise_auth_error("access token expired")
    return payload


def generate_refresh_token(session_id: UUID) -> tuple[str, str]:
    secret = secrets.token_urlsafe(32)
    return f"{session_id}.{secret}", hash_refresh_secret(secret)


def parse_refresh_token(token: str) -> tuple[UUID, str]:
    try:
        session_text, secret = token.split(".", 1)
        if not secret:
            raise ValueError
        return UUID(session_text), secret
    except Exception:
        raise_auth_error("invalid refresh token")


def hash_refresh_secret(secret: str) -> str:
    return hmac.new(
        JWT_SECRET_KEY.encode("utf-8"),
        secret.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def refresh_secret_matches(secret: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_refresh_secret(secret), expected_hash)


async def require_auth(request: Request) -> AuthContext:
    header = request.headers.get("Authorization", "")
    prefix = "Bearer "
    if not header.startswith(prefix):
        raise_auth_error("authorization bearer token missing")
    payload = decode_access_token(header[len(prefix) :].strip())
    try:
        user_id = UUID(str(payload["sub"]))
        session_id = UUID(str(payload["sid"]))
    except Exception:
        raise_auth_error("invalid access token claims")

    async with read_only_session() as db:
        session = await db.get(AuthSession, session_id)
        if (
            session is None
            or session.user_id != user_id
            or session.revoked_at is not None
            or is_expired(session.expires_at)
        ):
            raise_auth_error("auth session expired")

    return AuthContext(user_id=user_id, session_id=session_id)


def raise_auth_error(detail: str = "not authenticated"):
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _encode_jwt(payload: dict[str, Any]) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = ".".join(
        [
            _b64url_json(header),
            _b64url_json(payload),
        ]
    )
    signature = hmac.new(
        JWT_SECRET_KEY.encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return signing_input + "." + _b64url(signature)


def _decode_jwt(token: str) -> dict[str, Any]:
    try:
        header_text, payload_text, signature_text = token.split(".", 2)
        signing_input = f"{header_text}.{payload_text}"
        expected = hmac.new(
            JWT_SECRET_KEY.encode("utf-8"),
            signing_input.encode("ascii"),
            hashlib.sha256,
        ).digest()
        signature = _b64url_decode(signature_text)
        if not hmac.compare_digest(signature, expected):
            raise ValueError("bad signature")
        header = json.loads(_b64url_decode(header_text))
        if header.get("alg") != "HS256":
            raise ValueError("unsupported algorithm")
        payload = json.loads(_b64url_decode(payload_text))
        if not isinstance(payload, dict):
            raise ValueError("invalid payload")
        return payload
    except HTTPException:
        raise
    except Exception:
        raise_auth_error("invalid access token")


def _b64url_json(value: dict[str, Any]) -> str:
    return _b64url(json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
