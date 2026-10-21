import asyncio
import hashlib
import os
import re
import tempfile
import uuid
from pathlib import Path

import boto3
from botocore.config import Config
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import current_user
from .database import BackupMetadata, User, db_session
from .limits import BACKUP_LIMIT, BACKUP_MAX_ACTIVE, acquire_active_limit, enforce_rate_limit

router = APIRouter(prefix="/backup", tags=["backup"])

MAX_BACKUP_BYTES = int(os.getenv("BACKUP_MAX_BYTES", str(512 * 1024 * 1024)))
MAX_BACKUPS_PER_USER = int(os.getenv("BACKUP_RETENTION_COUNT", "5"))
_CHECKSUM = re.compile(r"^[0-9a-f]{64}$")


def create_r2_client():
    r2_access_key = os.getenv("R2_ACCESS_KEY_ID")
    r2_secret_key = os.getenv("R2_SECRET_ACCESS_KEY")
    r2_endpoint_url = os.getenv(
        "R2_ENDPOINT_URL",
        "https://8bf7553337b495f8a4148929387581c0.r2.cloudflarestorage.com",
    )
    if not r2_access_key or not r2_secret_key:
        raise RuntimeError("R2 credentials are not set in environment variables")

    session = boto3.session.Session()
    return session.client(
        service_name="s3",
        aws_access_key_id=r2_access_key,
        aws_secret_access_key=r2_secret_key,
        endpoint_url=r2_endpoint_url,
        config=Config(signature_version="s3v4"),
    )


def _bucket_name() -> str:
    bucket_name = os.getenv("R2_BUCKET_NAME")
    if not bucket_name:
        raise RuntimeError("R2_BUCKET_NAME is not set in environment variables")
    return bucket_name


def _declared_backup_size(request: Request) -> int:
    value = request.headers.get("content-length")
    if value is None:
        raise HTTPException(status_code=411, detail="Content-Length is required")
    try:
        size = int(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Content-Length is invalid") from exc
    if size < 1 or size > MAX_BACKUP_BYTES:
        raise HTTPException(status_code=413, detail="Backup exceeds the 512 MiB limit")
    return size


async def _retain_latest_five(r2, bucket_name: str, user_id: str, db: AsyncSession) -> None:
    stale_backups = await db.scalars(
        select(BackupMetadata)
        .where(BackupMetadata.user_id == user_id, BackupMetadata.checksum.is_not(None))
        .order_by(BackupMetadata.created_at.desc(), BackupMetadata.id.desc())
        .offset(MAX_BACKUPS_PER_USER)
    )
    for stale in stale_backups:
        await asyncio.to_thread(r2.delete_object, Bucket=bucket_name, Key=stale.object_name)
        await db.delete(stale)
    await db.commit()


@router.put("/upload")
async def upload_backup(
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/octet-stream":
        raise HTTPException(status_code=415, detail="Backup content must be application/octet-stream")
    declared_size = _declared_backup_size(request)
    expected_checksum = request.headers.get("x-backup-checksum", "")
    if not _CHECKSUM.fullmatch(expected_checksum):
        raise HTTPException(status_code=422, detail="X-Backup-Checksum must be a lowercase SHA-256 digest")

    await enforce_rate_limit("backup", user.id, BACKUP_LIMIT)
    lease = await acquire_active_limit("backup", user.id, BACKUP_MAX_ACTIVE)
    temp_path: Path | None = None
    try:
        digest = hashlib.sha256()
        received = 0
        with tempfile.NamedTemporaryFile(prefix="iatreon-backup-", suffix=".db", delete=False) as temporary:
            temp_path = Path(temporary.name)
            async for chunk in request.stream():
                received += len(chunk)
                if received > declared_size or received > MAX_BACKUP_BYTES:
                    raise HTTPException(status_code=413, detail="Backup exceeds the 512 MiB limit")
                digest.update(chunk)
                temporary.write(chunk)

        if received != declared_size:
            raise HTTPException(status_code=400, detail="Backup body does not match Content-Length")
        checksum = digest.hexdigest()
        if checksum != expected_checksum:
            raise HTTPException(status_code=422, detail="Backup checksum does not match body")

        backup_id = str(uuid.uuid4())
        object_key = f"users/{user.id}/backups/{backup_id}.db"
        r2 = create_r2_client()
        bucket_name = _bucket_name()
        await asyncio.to_thread(
            r2.upload_file,
            str(temp_path),
            bucket_name,
            object_key,
            ExtraArgs={"ContentType": "application/octet-stream"},
        )
        db.add(BackupMetadata(id=backup_id, user_id=user.id, object_name=object_key, checksum=checksum))
        await db.commit()
        await _retain_latest_five(r2, bucket_name, user.id, db)
        return {"status": "success", "backup_id": backup_id, "checksum": checksum}
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        await lease.release()


@router.get("/download/{backup_id}")
async def download_backup(
    backup_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
):
    metadata = await db.get(BackupMetadata, backup_id)
    if metadata is None or metadata.user_id != user.id:
        raise HTTPException(status_code=404, detail="Backup not found")
    if metadata.checksum is None:
        raise HTTPException(status_code=409, detail="Backup upload is not complete")

    r2 = create_r2_client()
    download_url = r2.generate_presigned_url(
        ClientMethod="get_object",
        Params={"Bucket": _bucket_name(), "Key": metadata.object_name},
        ExpiresIn=15 * 60,
    )
    return {"status": "success", "download_url": download_url, "checksum": metadata.checksum}


@router.get("/list")
async def list_backups(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
):
    result = await db.execute(
        select(BackupMetadata.id, BackupMetadata.checksum, BackupMetadata.created_at)
        .where(BackupMetadata.user_id == user.id, BackupMetadata.checksum.is_not(None))
        .order_by(BackupMetadata.created_at.desc())
    )
    return {"backups": [dict(backup) for backup in result.mappings()]}
