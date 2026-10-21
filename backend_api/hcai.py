import json
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.responses import StreamingResponse

from .auth import current_user
from .database import User
from .limits import HCAI_LIMIT, HCAI_MAX_ACTIVE, acquire_active_limit, enforce_rate_limit

from dotenv import load_dotenv

load_dotenv()

UPSTREAM_BASE_URL = "https://ai.hackclub.com/proxy/v1"
MAX_PROXY_BODY_BYTES = int(os.getenv("HCAI_MAX_REQUEST_BYTES", str(2 * 1024 * 1024)))
HTTP_TIMEOUT = httpx.Timeout(
    connect=float(os.getenv("HCAI_CONNECT_TIMEOUT_SECONDS", "10")),
    write=float(os.getenv("HCAI_WRITE_TIMEOUT_SECONDS", "30")),
    pool=float(os.getenv("HCAI_POOL_TIMEOUT_SECONDS", "10")),
    read=float(os.getenv("HCAI_READ_TIMEOUT_SECONDS", "300")),
)
HOP_BY_HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade",
}

router = APIRouter(dependencies=[Depends(current_user)], tags=["hcai"])


def _upstream_key() -> str:
    key = os.getenv("HCAI_API_KEY", "")
    if not key:
        raise RuntimeError("HCAI_API_KEY is required")
    return key


def _filtered_request_headers(headers) -> dict[str, str]:
    blocked = HOP_BY_HOP_HEADERS | {"host", "authorization", "content-length"}
    return {key: value for key, value in headers.items() if key.lower() not in blocked}


def _filtered_response_headers(headers) -> dict[str, str]:
    blocked = HOP_BY_HOP_HEADERS | {"content-encoding", "content-length"}
    return {key: value for key, value in headers.items() if key.lower() not in blocked}


async def _limited_body(request: Request) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_PROXY_BODY_BYTES:
                raise HTTPException(status_code=413, detail="Request body exceeds the 2 MiB limit")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Content-Length is invalid") from exc

    chunks = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > MAX_PROXY_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Request body exceeds the 2 MiB limit")
        chunks.append(chunk)
    return b"".join(chunks)


@router.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy(path: str, request: Request, user: User = Depends(current_user)) -> StreamingResponse:
    try:
        upstream_key = _upstream_key()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    await enforce_rate_limit("hcai", user.id, HCAI_LIMIT)
    lease = await acquire_active_limit("hcai", user.id, HCAI_MAX_ACTIVE)
    client = None
    try:
        headers = _filtered_request_headers(request.headers)
        headers["Authorization"] = f"Bearer {upstream_key}"
        headers["accept-encoding"] = "identity"
        request_body = await _limited_body(request)
        if "application/json" in request.headers.get("content-type", ""):
            try:
                payload = json.loads(request_body)
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=400, detail="Request body must be valid JSON") from exc
            if not isinstance(payload, dict):
                raise HTTPException(status_code=422, detail="Request JSON must be an object")
            payload["max_tokens"] = 2000
            request_body = json.dumps(payload).encode()

        client = httpx.AsyncClient(timeout=HTTP_TIMEOUT)
        upstream_request = client.build_request(
            request.method,
            f"{UPSTREAM_BASE_URL}/{path}",
            params=request.query_params.multi_items(),
            headers=headers,
            content=request_body,
        )
        upstream_response = await client.send(upstream_request, stream=True)
    except HTTPException:
        if client is not None:
            await client.aclose()
        await lease.release()
        raise
    except httpx.TimeoutException as exc:
        if client is not None:
            await client.aclose()
        await lease.release()
        raise HTTPException(status_code=504, detail="Hack Club AI proxy timed out") from exc
    except Exception as exc:
        if client is not None:
            await client.aclose()
        await lease.release()
        raise HTTPException(status_code=502, detail="Hack Club AI proxy unavailable") from exc

    async def stream_response():
        try:
            async for chunk in upstream_response.aiter_bytes():
                yield chunk
        finally:
            await upstream_response.aclose()
            await client.aclose()
            await lease.release()

    return StreamingResponse(
        stream_response(),
        status_code=upstream_response.status_code,
        headers=_filtered_response_headers(upstream_response.headers),
    )
