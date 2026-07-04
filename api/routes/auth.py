from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.security import (
    REFRESH_TOKEN_DAYS,
    create_access_token,
    generate_refresh_token,
    generate_session_key_salt,
    hash_password,
    is_expired,
    normalize_email,
    parse_refresh_token,
    refresh_secret_matches,
    utcnow,
    verify_password,
)
from db.db import unit_of_work
from db.models import AuthSession, User
from db.repositories import UserRepo

router = APIRouter(prefix="/auth", tags=["auth"])


class AuthCredentials(BaseModel):
    email: str
    password: str = Field(min_length=8)


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class AuthResponse(BaseModel):
    user_id: str
    email: str
    access_token: str
    refresh_token: str
    access_token_expires_at: datetime
    refresh_token_expires_at: datetime
    has_profile: bool
    session_key_salt: str


@router.post("/register", response_model=AuthResponse)
async def register(payload: AuthCredentials) -> AuthResponse:
    email = _email_or_400(payload.email)
    async with unit_of_work() as db:
        user_repo = UserRepo()
        if await user_repo.get_user_by_email(db, email):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="email already registered")
        user = await user_repo.create_user_with_password(
            db,
            email=email,
            password_hash=hash_password(payload.password),
            session_key_salt=generate_session_key_salt(),
        )
        return await _start_auth_session(db, user, user_repo)


@router.post("/login", response_model=AuthResponse)
async def login(payload: AuthCredentials) -> AuthResponse:
    email = _email_or_400(payload.email)
    async with unit_of_work() as db:
        user_repo = UserRepo()
        user = await user_repo.get_user_by_email(db, email)
        if user is None or not verify_password(payload.password, user.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid email or password")
        if not user.session_key_salt:
            user.session_key_salt = generate_session_key_salt()
        return await _start_auth_session(db, user, user_repo)


@router.post("/refresh", response_model=AuthResponse)
async def refresh(payload: RefreshRequest) -> AuthResponse:
    session_id, secret = parse_refresh_token(payload.refresh_token)
    async with unit_of_work() as db:
        stmt = select(AuthSession).where(AuthSession.id == session_id).with_for_update()
        session = (await db.execute(stmt)).scalar_one_or_none()
        if session is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid refresh token")
        if session.revoked_at is not None or is_expired(session.expires_at):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="refresh token expired")
        if not refresh_secret_matches(secret, session.refresh_token_hash):
            session.revoked_at = utcnow()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="refresh token reused")

        user = await db.get(User, session.user_id)
        if user is None:
            session.revoked_at = utcnow()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found")

        refresh_token, refresh_hash = generate_refresh_token(session.id)
        session.refresh_token_hash = refresh_hash
        session.last_used_at = utcnow()
        access_token, access_expires_at = create_access_token(user.id, session.id)
        return await _auth_response(
            db,
            user,
            access_token,
            refresh_token,
            access_expires_at,
            session.expires_at,
            UserRepo(),
        )


@router.post("/logout")
async def logout(payload: LogoutRequest) -> dict:
    session_id, secret = parse_refresh_token(payload.refresh_token)
    async with unit_of_work() as db:
        session = await db.get(AuthSession, session_id)
        if session is None:
            return {"status": "success"}
        if not refresh_secret_matches(secret, session.refresh_token_hash):
            session.revoked_at = utcnow()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid refresh token")
        session.revoked_at = utcnow()
        return {"status": "success"}


async def _start_auth_session(db, user: User, user_repo: UserRepo) -> AuthResponse:
    refresh_expires_at = utcnow() + timedelta(days=REFRESH_TOKEN_DAYS)
    session = AuthSession(
        user_id=user.id,
        refresh_token_hash="",
        expires_at=refresh_expires_at,
    )
    db.add(session)
    await db.flush()

    refresh_token, refresh_hash = generate_refresh_token(session.id)
    session.refresh_token_hash = refresh_hash
    access_token, access_expires_at = create_access_token(user.id, session.id)
    return await _auth_response(
        db,
        user,
        access_token,
        refresh_token,
        access_expires_at,
        refresh_expires_at,
        user_repo,
    )


async def _auth_response(
    db,
    user: User,
    access_token: str,
    refresh_token: str,
    access_expires_at: datetime,
    refresh_expires_at: datetime,
    user_repo: UserRepo,
) -> AuthResponse:
    return AuthResponse(
        user_id=str(user.id),
        email=user.email or "",
        access_token=access_token,
        refresh_token=refresh_token,
        access_token_expires_at=access_expires_at,
        refresh_token_expires_at=refresh_expires_at,
        has_profile=await user_repo.has_user_profile(db, user.id),
        session_key_salt=user.session_key_salt or "",
    )


def _email_or_400(email: str) -> str:
    try:
        return normalize_email(email)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
