from pathlib import Path
import hashlib
import base64

from local_worker.store.database import sqlcipher
from local_worker.store.backend_session import backend_api_url, get_backend_session

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

    async with httpx.AsyncClient() as client:
        response = await client.post(api_url, headers=headers, timeout=30)
        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to request backup upload: {response.status_code} {response.text}"
            )
        upload_url_request = response.json()
        upload_url = upload_url_request["upload_url"]
        backup_id = upload_url_request["backup_id"]

        with backup_path.open("rb") as file:
            response = await client.put(
                upload_url,
                data=file,
                headers={"Content-Type": "application/octet-stream"},
                timeout=300,
            )
            if response.status_code != 200:
                raise RuntimeError(f"Failed to upload backup: {response.status_code} {response.text}")

        response = await client.post(
            api_url + f"/{backup_id}/complete",
            json={"checksum": checksum},
            headers=headers,
            timeout=30,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to complete backup upload: {response.status_code} {response.text}"
            )


async def download_backup(backup_id: str, user_id: str, destination_path: Path) -> None:
    import httpx

    api_url = backend_api_url() + f"/backup/download/{backup_id}"
    access_token = get_backend_session(user_id).get("access_token")
    if not access_token:
        raise RuntimeError("No access token found for user, cannot download backup")

    headers = {"Authorization": f"Bearer {access_token}"}

    async with httpx.AsyncClient() as client:
        response = await client.get(api_url, headers=headers, timeout=30)
        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to request backup download: {response.status_code} {response.text}"
            )
        download_url_request = response.json()
        download_url = download_url_request["download_url"]

        response = await client.get(download_url, timeout=300)
        if response.status_code != 200:
            raise RuntimeError(f"Failed to download backup: {response.status_code} {response.text}")

        destination_path.parent.mkdir(parents=True, exist_ok=True)
        with destination_path.open("wb") as file:
            file.write(response.content)

    checksum = calculate_sha256(destination_path)
    if checksum != download_url_request["checksum"]:
        raise RuntimeError(
            "Downloaded backup checksum does not match: "
            f"{checksum} != {download_url_request['checksum']}"
        )
