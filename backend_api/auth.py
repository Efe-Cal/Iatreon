import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, status
from jwt import InvalidTokenError
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from .database import User, db_session


JWT_ALG = "HS256"
PBKDF2_ITERATIONS = 210_000
router = APIRouter(prefix="/auth", tags=["auth"])


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=1024)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    username: str


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)


def _jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET", "")
    if not secret:
        raise RuntimeError("JWT_SECRET is required")
    return secret


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt_bytes = _b64url_decode(salt) if salt else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt_bytes, PBKDF2_ITERATIONS)
    return _b64url(digest), _b64url(salt_bytes)


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    got, _ = hash_password(password, salt)
    return hmac.compare_digest(got, password_hash)


def create_jwt(user: User) -> str:
    now = datetime.now(timezone.utc)
    ttl = int(os.getenv("JWT_TTL_SECONDS", str(30 * 24 * 60 * 60)))
    payload = {
        "sub": user.id,
        "username": user.username,
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALG)


def verify_jwt(token: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            _jwt_secret(),
            algorithms=[JWT_ALG],
            options={"require": ["exp", "sub"]},
        )
        if not isinstance(payload.get("sub"), str) or not payload["sub"]:
            raise InvalidTokenError("invalid subject")
        return payload
    except (InvalidTokenError, RuntimeError) as exc:
        raise HTTPException(status_code=401, detail="invalid bearer token") from exc


async def current_user(
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(db_session),
) -> User:
    if not authorization:
        raise HTTPException(status_code=401, detail="bearer token required")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="bearer token required")
    payload = verify_jwt(token.strip())
    user = await db.get(User, payload["sub"])
    if user is None:
        raise HTTPException(status_code=401, detail="invalid bearer token")
    return user


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(credentials: Credentials, db: AsyncSession = Depends(db_session)) -> TokenResponse:
    username = credentials.username.strip()
    if not username:
        raise HTTPException(status_code=422, detail="username is required")
    password_hash, salt = hash_password(credentials.password)
    user = User(username=username, password_hash=password_hash, password_salt=salt)
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="username already exists") from exc
    await db.refresh(user)
    return TokenResponse(access_token=create_jwt(user))


@router.post("/token", response_model=TokenResponse)
async def token(credentials: Credentials, db: AsyncSession = Depends(db_session)) -> TokenResponse:
    username = credentials.username.strip()
    user = await db.scalar(select(User).where(User.username == username))
    if user is None:
        hash_password(credentials.password)
        raise HTTPException(status_code=401, detail="invalid username or password")
    if not verify_password(credentials.password, user.password_hash, user.password_salt):
        raise HTTPException(status_code=401, detail="invalid username or password")
    return TokenResponse(access_token=create_jwt(user))


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(current_user)) -> UserResponse:
    return UserResponse(id=user.id, username=user.username)
