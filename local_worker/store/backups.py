import asyncio
import base64
import hashlib
import os
from pathlib import Path

from local_worker.store.database import sqlcipher
from local_worker.store.backend_session import backend_api_url, get_backend_session


def _http_timeout():
    # Imported lazily so the backup creation path does not need HTTPX.
    import httpx

    return httpx.Timeout(connect=10, write=30, pool=10, read=300)


def calculate_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


async def create_encrypted_backup(source_path: Path, backup_path: Path, db_key: str) -> str:
    if not source_path.exists():
        raise FileNotFoundError(f"Source database file does not exist: {source_path}")

    backup_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path.unlink(missing_ok=True)

    source_connection = sqlcipher.connect(str(source_path), check_same_thread=False)
    backup_connection = sqlcipher.connect(str(backup_path), check_same_thread=False)

    key = base64.b64decode(db_key, validate=True)
    key_hex = key.hex()

    try:
        source_connection.execute(f"PRAGMA key = \"x'{key_hex}'\"")
        backup_connection.execute(f"PRAGMA key = \"x'{key_hex}'\"")

        source_connection.execute("SELECT count(*) FROM sqlite_master")

        source_connection.backup(backup_connection)
        backup_connection.commit()

        result = backup_connection.execute("PRAGMA cipher_integrity_check").fetchall()

        if result:
            raise RuntimeError(f"Backup integrity check failed: {result}")

    except Exception:
        backup_connection.close()
        source_connection.close()
        backup_path.unlink(missing_ok=True)
        raise
    else:
        backup_connection.close()
        source_connection.close()

    if not backup_path.is_file() or backup_path.stat().st_size == 0:
        backup_path.unlink(missing_ok=True)
        raise RuntimeError("Backup file was not created correctly")

    return calculate_sha256(backup_path)


async def upload_backup(backup_path: Path, user_id: str, checksum: str) -> None:
    import httpx

    if not backup_path.is_file() or backup_path.stat().st_size == 0:
        raise FileNotFoundError(f"Backup file does not exist or is empty: {backup_path}")

    api_url = backend_api_url() + "/backup/upload"
    access_token = get_backend_session(user_id).get("access_token")
    if not access_token:
        raise RuntimeError("No access token found for user, cannot upload backup")

    headers = {"Authorization": f"Bearer {access_token}"}

    async def file_chunks():
        with backup_path.open("rb") as file:
            while chunk := await asyncio.to_thread(file.read, 1024 * 1024):
                yield chunk

    upload_headers = {
        **headers,
        "Content-Type": "application/octet-stream",
        "Content-Length": str(backup_path.stat().st_size),
        "X-Backup-Checksum": checksum,
    }
    async with httpx.AsyncClient(timeout=_http_timeout()) as client:
        response = await client.put(api_url, content=file_chunks(), headers=upload_headers)
    if response.status_code != 200:
        raise RuntimeError(f"Failed to upload backup: {response.status_code} {response.text}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("Backup upload returned an invalid response") from exc
    if payload.get("checksum") != checksum or not payload.get("backup_id"):
        raise RuntimeError("Backup upload returned an invalid response")


async def download_backup(backup_id: str, user_id: str, destination_path: Path) -> None:
    import httpx

    api_url = backend_api_url() + f"/backup/download/{backup_id}"
    access_token = get_backend_session(user_id).get("access_token")
    if not access_token:
        raise RuntimeError("No access token found for user, cannot download backup")

    headers = {"Authorization": f"Bearer {access_token}"}

    async with httpx.AsyncClient(timeout=_http_timeout()) as client:
        response = await client.get(api_url, headers=headers)
        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to request backup download: {response.status_code} {response.text}"
            )
        download_url_request = response.json()
        download_url = download_url_request["download_url"]

        destination_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            async with client.stream("GET", download_url) as response:
                if response.status_code != 200:
                    raise RuntimeError(f"Failed to download backup: {response.status_code} {response.text}")
                with destination_path.open("wb") as file:
                    async for chunk in response.aiter_bytes(1024 * 1024):
                        file.write(chunk)
        except Exception:
            destination_path.unlink(missing_ok=True)
            raise

    checksum = calculate_sha256(destination_path)
    if checksum != download_url_request["checksum"]:
        raise RuntimeError(
            "Downloaded backup checksum does not match: "
            f"{checksum} != {download_url_request['checksum']}"
        )


async def restore_backup(
    user_id: str,
    backup_id: str,
    restore_path: Path,
    checksum: str,
    db_key: str,
) -> None:
    downloaded_backup_temp_path = Path(f"{restore_path}.backup.tmp")

    try:
        await download_backup(
            backup_id,
            user_id=user_id,
            destination_path=downloaded_backup_temp_path,
        )

        downloaded_checksum = calculate_sha256(downloaded_backup_temp_path)
        if downloaded_checksum != checksum:
            raise RuntimeError(
                "Downloaded backup checksum does not match provided checksum: "
                f"{downloaded_checksum} != {checksum}"
            )

        temp_connection = sqlcipher.connect(
            str(downloaded_backup_temp_path),
            check_same_thread=False,
        )
        try:
            key_hex = base64.b64decode(db_key, validate=True).hex()
            temp_connection.execute(f"PRAGMA key = \"x'{key_hex}'\"")
            temp_connection.execute("SELECT count(*) FROM sqlite_master").fetchone()
            result = temp_connection.execute("PRAGMA cipher_integrity_check").fetchall()
            if result:
                raise RuntimeError(f"Backup integrity check failed: {result}")
        finally:
            temp_connection.close()

        os.replace(downloaded_backup_temp_path, restore_path)

    finally:
        downloaded_backup_temp_path.unlink(missing_ok=True)


async def list_backups(user_id: str) -> list[dict]:
    import httpx

    api_url = backend_api_url() + "/backup/list"
    access_token = get_backend_session(user_id).get("access_token")
    if not access_token:
        raise RuntimeError("No access token found for user, cannot list backups")

    headers = {"Authorization": f"Bearer {access_token}"}

    async with httpx.AsyncClient() as client:
        response = await client.get(api_url, headers=headers, timeout=30)
        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to list backups: {response.status_code} {response.text}"
            )
        return response.json().get("backups", [])
