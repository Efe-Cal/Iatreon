from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sshpubkeys import SSHKey

from api.shared import clear_encryption_context, require_encryption_context
from db.db import unit_of_work
from db.repositories import UserRepo
from db.schemas import UserProfileData

router = APIRouter()

def _validate_ssh_public_key(value: str) -> str:

    if not isinstance(value, str):
        raise ValueError('ssh_key must be a string')

    key_text = value.strip()
    if not key_text:
        raise ValueError('ssh_key is required')

    try:
        key = SSHKey(key_text, strict=True)
        key.parse()
    except (ValueError, Exception) as exc:
        raise ValueError(f'invalid or insecure SSH public key: {exc}') from exc

    if not key.key_type:
        raise ValueError('invalid SSH public key: missing key type')

    return key_text


class GetOrCreateUserRequest(BaseModel):
    ssh_key: str = Field(..., description='OpenSSH public key')

    @field_validator('ssh_key')
    @classmethod
    def _validate_ssh_key(cls, value: str) -> str:
        return _validate_ssh_public_key(value)


@router.post('/user')
async def get_or_create_user(payload: GetOrCreateUserRequest) -> dict:
    ssh_key = payload.ssh_key
    if not ssh_key:
        return {'error': 'ssh_key is required'}
    async with unit_of_work() as db:
        user_repo = UserRepo()
        user_id = await user_repo.get_user_id_by_ssh_key(db, ssh_key)
        if not user_id:
            user = await user_repo.create_user(db, ssh_key)
            return {'user_id': str(user.id), 'has_profile': False}
        return {'user_id': str(user_id), 'has_profile': await user_repo.has_user_profile(db, user_id)}


@router.post('/user/session')
async def unlock_user_session(user_id: UUID, request: Request) -> dict:
    token = require_encryption_context(request)
    try:
        async with unit_of_work() as db:
            user_repo = UserRepo()
            await user_repo.initialize_user_encryption(db, user_id)
            profile = await user_repo.get_user_profile(db, user_id)
            return {'status': 'unlocked', 'has_profile': bool(profile)}
    finally:
        clear_encryption_context(token)


@router.get('/user-profile')
async def get_user_profile(user_id: UUID, request: Request) -> dict:
    token = require_encryption_context(request)
    try:
        async with unit_of_work() as db:
            user_repo = UserRepo()
            profile = await user_repo.get_user_profile(db, user_id)
            return profile
    finally:
        clear_encryption_context(token)


@router.post('/user-profile')
async def update_user_profile(profile_data: UserProfileData, request: Request) -> dict:
    token = require_encryption_context(request)
    try:
        async with unit_of_work() as db:
            user_repo = UserRepo()
            await user_repo.update_user_profile(db, profile_data)
            return {'status': 'success'}
    finally:
        clear_encryption_context(token)
