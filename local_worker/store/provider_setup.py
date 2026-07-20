from typing import Any

from local_worker.store.database import _session, _lock
from local_worker.store.tables import ProviderSetup






def update_provider_setup(payload: dict[str, Any]) -> None:
    with _lock, _session() as db:
        user_id = str(payload["user_id"])
        row = db.get(ProviderSetup, user_id)
        if row is None:
            db.add(ProviderSetup(user_id=user_id, payload=payload))
        else:
            row.payload = payload
        db.commit()


def get_provider_setup(user_id: str) -> dict[str, Any]:
    with _lock, _session() as db:
        row = db.get(ProviderSetup, str(user_id))
        return row.payload if row else {}


def has_provider_setup(user_id: str) -> bool:
    with _lock, _session() as db:
        return db.get(ProviderSetup, str(user_id)) is not None