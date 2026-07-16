import os
import uuid

import boto3
from botocore.config import Config
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import current_user
from .database import BackupMetadata, User, db_session

router = APIRouter(prefix="/backup", tags=["backup"])


class BackupCompleteRequest(BaseModel):
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")


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
    s3_client = session.client(
        service_name="s3",
        aws_access_key_id=r2_access_key,
        aws_secret_access_key=r2_secret_key,
        endpoint_url=r2_endpoint_url,
        config=Config(signature_version="s3v4"),
    )
    return s3_client


@router.post("/upload")
async def upload_backup(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
):
    backup_id = str(uuid.uuid4())
    object_key = f"users/{user.id}/backups/{backup_id}.db"
    r2 = create_r2_client()
    bucket_name = os.getenv("R2_BUCKET_NAME")
    if not bucket_name:
        raise RuntimeError("R2_BUCKET_NAME is not set in environment variables")

    upload_url = r2.generate_presigned_url(
        ClientMethod="put_object",
        Params={
            "Bucket": bucket_name,
            "Key": object_key,
            "ContentType": "application/octet-stream",
        },
        ExpiresIn=15 * 60,
    )

    db.add(BackupMetadata(id=backup_id, user_id=user.id, object_name=object_key))
    await db.commit()

    return {"status": "success", "upload_url": upload_url, "backup_id": backup_id}


@router.post("/upload/{backup_id}/complete")
async def complete_upload(
    backup_id: str,
    payload: BackupCompleteRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
):
    metadata = await db.get(BackupMetadata, backup_id)
    if metadata is None:
        raise HTTPException(status_code=404, detail="Backup record not found")
    if metadata.user_id != user.id:
        raise HTTPException(status_code=403, detail="Unauthorized to update this backup")

    metadata.checksum = payload.checksum
    await db.commit()
    return {"status": "success", "message": "Backup metadata stored successfully."}


@router.get("/download/{backup_id}")
async def download_backup(
    backup_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
):
    metadata = await db.get(BackupMetadata, backup_id)
    if metadata is None:
        raise HTTPException(status_code=404, detail="Backup record not found")
    if metadata.user_id != user.id:
        raise HTTPException(status_code=403, detail="Unauthorized to access this backup")
    if metadata.checksum is None:
        raise HTTPException(status_code=409, detail="Backup upload is not complete")

    r2 = create_r2_client()
    bucket_name = os.getenv("R2_BUCKET_NAME")
    if not bucket_name:
        raise RuntimeError("R2_BUCKET_NAME is not set in environment variables")

    download_url = r2.generate_presigned_url(
        ClientMethod="get_object",
        Params={
            "Bucket": bucket_name,
            "Key": metadata.object_name,
        },
        ExpiresIn=15 * 60,
    )

    return {"status": "success", "download_url": download_url, "checksum": metadata.checksum}
