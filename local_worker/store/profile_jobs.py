import time
from typing import Any

from local_worker.store.database import _lock, _session
from local_worker.store.tables import ProfileUpdateJob

from sqlalchemy.orm import Session
from sqlalchemy import  select, text


PROFILE_JOB_LEASE_SECONDS = 15 * 60


def upsert_profile_update_job(
    user_id: str,
    chat_session_id: str | None,
    delay_seconds: float = 0,
) -> None:
    if not chat_session_id:
        return

    with _lock, _session() as db:
        _queue_profile_update(db, user_id, chat_session_id, delay_seconds)
        db.commit()


def _queue_profile_update(
    db: Session,
    user_id: str,
    chat_session_id: str | None,
    delay_seconds: float = 0,
) -> None:
    if not chat_session_id:
        return
    timestamp = time.time()
    row = db.get(ProfileUpdateJob, str(chat_session_id))
    if row is None:
        db.add(ProfileUpdateJob(
            chat_session_id=str(chat_session_id),
            user_id=str(user_id),
            dirty_at=timestamp,
            next_attempt_at=timestamp + delay_seconds,
        ))
        return
    if row.user_id != str(user_id):
        raise ValueError("Chat session belongs to another user.")
    row.dirty_at = timestamp
    row.next_attempt_at = timestamp + delay_seconds
    row.revision += 1
    row.attempts = 0
    row.last_error = None
    if row.status != "running":
        row.status = "pending"
        row.claimed_at = None


def claim_profile_update_job(lease_seconds: float = PROFILE_JOB_LEASE_SECONDS) -> dict[str, Any] | None:
    timestamp = time.time()
    with _lock, _session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        for stale in db.scalars(select(ProfileUpdateJob).where(
            ProfileUpdateJob.status == "running",
            ProfileUpdateJob.claimed_at <= timestamp - lease_seconds,
        )):
            stale.status = "pending"
            stale.claimed_at = None

        running_users = select(ProfileUpdateJob.user_id).where(ProfileUpdateJob.status == "running")
        row = db.scalars(
            select(ProfileUpdateJob)
            .where(
                ProfileUpdateJob.status == "pending",
                ProfileUpdateJob.next_attempt_at <= timestamp,
                ProfileUpdateJob.user_id.not_in(running_users),
            )
            .order_by(ProfileUpdateJob.next_attempt_at, ProfileUpdateJob.dirty_at)
            .limit(1)
        ).first()
        if row is None:
            db.commit()
            return None

        row.status = "running"
        row.claimed_at = timestamp
        job = {
            "user_id": row.user_id,
            "chat_session_id": row.chat_session_id,
            "revision": row.revision,
        }
        db.commit()
        return job


def complete_profile_update_job(chat_session_id: str, revision: int) -> None:
    with _lock, _session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        row = db.get(ProfileUpdateJob, str(chat_session_id))
        if row is None:
            db.commit()
            return
        if row.revision == revision:
            db.delete(row)
        else:
            row.status = "pending"
            row.claimed_at = None
        db.commit()


def fail_profile_update_job(chat_session_id: str, revision: int, error: str) -> None:
    with _lock, _session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        row = db.get(ProfileUpdateJob, str(chat_session_id))
        if row is None:
            db.commit()
            return
        row.status = "pending"
        row.claimed_at = None
        if row.revision == revision:
            row.attempts += 1
            row.next_attempt_at = time.time() + min(3600, 30 * (2 ** (row.attempts - 1)))
            row.last_error = error[-2000:]
        db.commit()


def next_profile_update_delay() -> float | None:
    with _lock, _session() as db:
        claimed_at = db.scalars(
            select(ProfileUpdateJob.claimed_at)
            .where(ProfileUpdateJob.status == "running")
            .order_by(ProfileUpdateJob.claimed_at)
            .limit(1)
        ).first()
        if claimed_at is not None:
            return max(0, claimed_at + PROFILE_JOB_LEASE_SECONDS - time.time())
        next_attempt = db.scalars(
            select(ProfileUpdateJob.next_attempt_at)
            .where(ProfileUpdateJob.status == "pending")
            .order_by(ProfileUpdateJob.next_attempt_at)
            .limit(1)
        ).first()
        return max(0, next_attempt - time.time()) if next_attempt is not None else None


def has_pending_profile_update_jobs() -> bool:
    with _lock, _session() as db:
        return db.scalars(
            select(ProfileUpdateJob.chat_session_id)
            .where(ProfileUpdateJob.status == "pending")
            .limit(1)
        ).first() is not None