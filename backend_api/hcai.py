import os

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse

from .auth import current_user

from dotenv import load_dotenv

load_dotenv()

UPSTREAM_BASE_URL = "https://ai.hackclub.com/proxy/v1"
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


@router.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy(path: str, request: Request) -> StreamingResponse:
    try:
        upstream_key = _upstream_key()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    async def request_body():
        async for chunk in request.stream():
            yield chunk

    headers = _filtered_request_headers(request.headers)
    headers["Authorization"] = f"Bearer {upstream_key}"
    client = httpx.AsyncClient(timeout=None)
    upstream_request = client.build_request(
        request.method,
        f"{UPSTREAM_BASE_URL}/{path}",
        params=request.query_params.multi_items(),
        headers=headers,
        content=request_body(),
    )
    try:
        upstream_response = await client.send(upstream_request, stream=True)
    except Exception as exc:
        await client.aclose()
        raise HTTPException(status_code=502, detail="Hack Club AI proxy unavailable") from exc

    async def close_upstream() -> None:
        await upstream_response.aclose()
        await client.aclose()

    return StreamingResponse(
        upstream_response.aiter_bytes(),
        status_code=upstream_response.status_code,
        headers=_filtered_response_headers(upstream_response.headers),
        background=BackgroundTask(close_upstream),
    )
