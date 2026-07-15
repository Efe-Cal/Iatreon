import base64
import hashlib
import hmac
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, status
from jwt import InvalidTokenError
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from .database import RefreshToken, User, db_session

from dotenv import load_dotenv

load_dotenv()

JWT_ALG = "HS256"
PBKDF2_ITERATIONS = 210_000
router = APIRouter(prefix="/auth", tags=["auth"])


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=1024)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=1024)


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
    ttl = int(os.getenv("ACCESS_TOKEN_TTL_SECONDS", str(7 * 24 * 60 * 60)))
    payload = {
        "sub": user.id,
        "username": user.username,
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
        "typ": "access",
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALG)


def _refresh_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _refresh_ttl() -> timedelta:
    return timedelta(seconds=int(os.getenv("REFRESH_TOKEN_TTL_SECONDS", str(30 * 24 * 60 * 60))))




def _token_pair(user: User, family_id: str | None = None) -> tuple[TokenResponse, RefreshToken]:
    now = datetime.now(timezone.utc)
    refresh_token = secrets.token_urlsafe(48)
    row = RefreshToken(
        token_hash=_refresh_token_hash(refresh_token),
        family_id=family_id or str(uuid.uuid4()),
        user_id=user.id,
        expires_at=now + _refresh_ttl(),
    )
    return TokenResponse(access_token=create_jwt(user), refresh_token=refresh_token), row



def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def _invalid_refresh(db: AsyncSession, row: RefreshToken | None = None) -> None:
    if row is not None and row.revoked_at is not None:
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == row.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(timezone.utc))
        )
        await db.commit()
    raise HTTPException(status_code=401, detail="invalid refresh token")


def verify_jwt(token: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            _jwt_secret(),
            algorithms=[JWT_ALG],
            options={"require": ["exp", "sub", "typ"]},
        )
        if (
            not isinstance(payload.get("sub"), str)
            or not payload["sub"]
            or payload.get("typ") != "access"
        ):
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
        await db.flush()
        response, refresh_row = _token_pair(user)
        db.add(refresh_row)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="username already exists") from exc
    return response


@router.post("/token", response_model=TokenResponse)
async def token(credentials: Credentials, db: AsyncSession = Depends(db_session)) -> TokenResponse:
    username = credentials.username.strip()
    user = await db.scalar(select(User).where(User.username == username))
    if user is None:
        hash_password(credentials.password)
        raise HTTPException(status_code=401, detail="invalid username or password")
    if not verify_password(credentials.password, user.password_hash, user.password_salt):
        raise HTTPException(status_code=401, detail="invalid username or password")


    response, refresh_row = _token_pair(user)
    db.add(refresh_row)
    await db.commit()
    return response


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: RefreshRequest, db: AsyncSession = Depends(db_session)) -> TokenResponse:
    token_hash = _refresh_token_hash(request.refresh_token)
    row = await db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
    )
    if row is None or row.revoked_at is not None or _as_utc(row.expires_at) <= datetime.now(timezone.utc):
        await _invalid_refresh(db, row)

    user = await db.get(User, row.user_id)
    if user is None:
        row.revoked_at = datetime.now(timezone.utc)
        await db.commit()
        await _invalid_refresh(db)

    response, replacement = _token_pair(user, row.family_id)
    row.revoked_at = datetime.now(timezone.utc)

    db.add(replacement)
    await db.commit()
    return response


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(current_user)) -> UserResponse:
    return UserResponse(id=user.id, username=user.username)
