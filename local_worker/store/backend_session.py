import binascii
import os
import time
import json
import base64
import httpx

from local_worker.store.database import _session, _lock
from local_worker.store.tables import BackendSession
from local_worker.request_context import current_user_id


ACCESS_REFRESH_LEEWAY_SECONDS = 5 * 60

class BackendAuthRequired(RuntimeError):
    pass


class BackendAuthUnavailable(RuntimeError):
    pass

def backend_api_url() -> str:
    return os.getenv("IATREON_BACKEND_API_URL", "https://iatreon.efecal.hackclub.app").rstrip("/")
    

def update_backend_session(user_id: str, username: str, access_token: str, refresh_token: str) -> None:
    with _lock, _session() as db:
        row = db.get(BackendSession, str(user_id))
        if row is None:
            db.add(BackendSession(
                user_id=str(user_id),
                username=username,
                access_token=access_token,
                refresh_token=refresh_token,
            ))
        else:
            row.username = username
            row.access_token = access_token
            row.refresh_token = refresh_token
        db.commit()


def get_backend_session(user_id: str) -> dict[str, str]:
    with _lock, _session() as db:
        row = db.get(BackendSession, str(user_id))
        if row is None:
            return {}
        return {
            "username": row.username,
            "access_token": row.access_token,
            "refresh_token": row.refresh_token,
        }


def has_backend_session(user_id: str) -> bool:
    with _lock, _session() as db:
        return db.get(BackendSession, str(user_id)) is not None



def backend_session() -> dict[str, str]:
    if os.getenv("IATREON_LOCAL_WORKER") != "1":
        return {"access_token": os.getenv("IATREON_BACKEND_API_TOKEN", "")}
    user_id = current_user_id()
    if not user_id:
        return {}

    from local_worker.store.backend_session import get_backend_session

    return get_backend_session(user_id)



def _access_expires_soon(token: str) -> bool:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        expires_at = float(json.loads(base64.urlsafe_b64decode(payload))["exp"])
        return expires_at <= time.time() + ACCESS_REFRESH_LEEWAY_SECONDS
    except (IndexError, KeyError, TypeError, ValueError, binascii.Error):
        return True

async def ensure_backend_session(user_id: str | None = None, validate: bool = False) -> dict[str, str]:
    if os.getenv("IATREON_LOCAL_WORKER") != "1":
        return backend_session()

    from local_worker.store.backend_session import get_backend_session, update_backend_session

    user_id = str(user_id or current_user_id() or "")
    session = get_backend_session(user_id) if user_id else {}
    access_token = session.get("access_token", "")
    refresh_token = session.get("refresh_token", "")
    if not refresh_token:
        raise BackendAuthRequired("Your session has expired. Please sign in again.")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            if access_token and not _access_expires_soon(access_token):
                if not validate:
                    return session
                response = await client.get(
                    backend_api_url() + "/auth/me",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if response.status_code == 200:
                    return session
                if response.status_code != 401:
                    raise BackendAuthUnavailable("Iatreon authentication is temporarily unavailable.")

            response = await client.post(
                backend_api_url() + "/auth/refresh",
                json={"refresh_token": refresh_token},
            )
    except httpx.HTTPError as exc:
        raise BackendAuthUnavailable("Iatreon authentication is temporarily unavailable.") from exc

    if response.status_code == 401:
        raise BackendAuthRequired("Your session has expired. Please sign in again.")
    if response.status_code != 200:
        raise BackendAuthUnavailable("Iatreon authentication is temporarily unavailable.")

    try:
        payload = response.json()
        access_token = payload["access_token"]
        refresh_token = payload["refresh_token"]
        if not access_token or not refresh_token:
            raise ValueError
    except (KeyError, TypeError, ValueError) as exc:
        raise BackendAuthUnavailable("Iatreon authentication returned an invalid response.") from exc

    update_backend_session(user_id, session.get("username", ""), access_token, refresh_token)
    return get_backend_session(user_id)
