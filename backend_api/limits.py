"""Fail-closed Redis resource limits for public backend routes."""

import hashlib
import os
from dataclasses import dataclass

from fastapi import HTTPException

try:
    from redis import asyncio as redis_asyncio
    from redis.exceptions import RedisError
except ImportError:  # pragma: no cover - deployment packaging concern
    redis_asyncio = None

    class RedisError(Exception):
        pass


class RedisUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class RateLimit:
    count: int
    window_seconds: int


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be positive")
    return value


# Secure defaults for the current small shared deployment. Every value is
# configurable without changing code so operators can tune real traffic.
REGISTER_LIMIT = RateLimit(
    _positive_int("BACKEND_REGISTER_RATE_COUNT", 5),
    _positive_int("BACKEND_REGISTER_RATE_WINDOW_SECONDS", 60 * 60),
)
LOGIN_IP_LIMIT = RateLimit(
    _positive_int("BACKEND_LOGIN_IP_RATE_COUNT", 10),
    _positive_int("BACKEND_LOGIN_IP_RATE_WINDOW_SECONDS", 60),
)
LOGIN_USER_LIMIT = RateLimit(
    _positive_int("BACKEND_LOGIN_USER_RATE_COUNT", 5),
    _positive_int("BACKEND_LOGIN_USER_RATE_WINDOW_SECONDS", 5 * 60),
)
HCAI_LIMIT = RateLimit(
    _positive_int("BACKEND_HCAI_RATE_COUNT", 60),
    _positive_int("BACKEND_HCAI_RATE_WINDOW_SECONDS", 60),
)
PDF_LIMIT = RateLimit(
    _positive_int("BACKEND_PDF_RATE_COUNT", 30),
    _positive_int("BACKEND_PDF_RATE_WINDOW_SECONDS", 60 * 60),
)
BACKUP_LIMIT = RateLimit(
    _positive_int("BACKEND_BACKUP_RATE_COUNT", 3),
    _positive_int("BACKEND_BACKUP_RATE_WINDOW_SECONDS", 60 * 60),
)
HCAI_MAX_ACTIVE = _positive_int("BACKEND_HCAI_MAX_ACTIVE", 3)
PDF_MAX_ACTIVE = _positive_int("BACKEND_PDF_MAX_ACTIVE", 3)
BACKUP_MAX_ACTIVE = _positive_int("BACKEND_BACKUP_MAX_ACTIVE", 1)
ACTIVE_LEASE_SECONDS = _positive_int("BACKEND_ACTIVE_LEASE_SECONDS", 10 * 60)

_redis = None

_RELEASE_ACTIVE_SCRIPT = """
if redis.call('DECR', KEYS[1]) <= 0 then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


def _redis_url() -> str:
    if configured := os.getenv("REDIS_URL"):
        return configured
    host = os.getenv("REDIS_HOST", "redis")
    port = os.getenv("REDIS_PORT", "6379")
    return f"redis://{host}:{port}/0"


async def _client():
    global _redis
    if _redis is not None:
        return _redis
    if redis_asyncio is None:
        raise RedisUnavailable("Redis support is unavailable")
    _redis = redis_asyncio.from_url(_redis_url(), decode_responses=True)
    try:
        await _redis.ping()
    except RedisError as exc:
        _redis = None
        raise RedisUnavailable("Redis is unavailable") from exc
    return _redis


async def redis_ready() -> bool:
    try:
        client = await _client()
        return bool(await client.ping())
    except (RedisError, RedisUnavailable):
        return False


async def close_redis() -> None:
    global _redis
    client, _redis = _redis, None
    close = getattr(client, "aclose", None)
    if close is not None:
        await close()


def _unavailable(exc: Exception) -> HTTPException:
    return HTTPException(status_code=503, detail="Resource limits are temporarily unavailable")


async def enforce_rate_limit(scope: str, identity: str, limit: RateLimit) -> None:
    key = f"iatreon:limit:{scope}:{identity}"
    try:
        client = await _client()
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, limit.window_seconds)
        ttl = await client.ttl(key)
    except (RedisError, RedisUnavailable) as exc:
        raise _unavailable(exc) from exc

    if count > limit.count:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(max(1, ttl if ttl > 0 else limit.window_seconds))},
        )


class ActiveLease:
    def __init__(self, key: str):
        self._key = key
        self._released = False

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        try:
            client = await _client()
            await client.eval(_RELEASE_ACTIVE_SCRIPT, 1, self._key)
        except (RedisError, RedisUnavailable):
            # The expiry bounds a leaked lease if Redis becomes unavailable while
            # a response stream is closing.
            return


async def acquire_active_limit(scope: str, identity: str, maximum: int) -> ActiveLease:
    key = f"iatreon:active:{scope}:{identity}"
    try:
        client = await _client()
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, ACTIVE_LEASE_SECONDS)
        ttl = await client.ttl(key)
        if count > maximum:
            await client.decr(key)
            raise HTTPException(
                status_code=429,
                detail="Too many active requests",
                headers={"Retry-After": str(max(1, ttl if ttl > 0 else ACTIVE_LEASE_SECONDS))},
            )
    except HTTPException:
        raise
    except (RedisError, RedisUnavailable) as exc:
        raise _unavailable(exc) from exc
    return ActiveLease(key)


def client_identity(request) -> str:
    return request.client.host if request.client else "unknown"


def username_identity(username: str) -> str:
    normalized = username.strip().casefold().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()
