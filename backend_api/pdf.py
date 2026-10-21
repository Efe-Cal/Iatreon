import os

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from .auth import current_user
from .database import PDFJob, User, db_session
from .limits import PDF_LIMIT, PDF_MAX_ACTIVE, acquire_active_limit, enforce_rate_limit


router = APIRouter(prefix="/api/v1/pdf", tags=["pdf"])
HTTP_TIMEOUT = httpx.Timeout(connect=10, write=30, pool=10, read=300)


class PDFJobRequest(BaseModel):
    pdf_url: HttpUrl


class PDFJobResponse(BaseModel):
    job_id: str
    status: str


def _worker_url() -> str:
    return os.getenv("PDF_WORKER_BASE_URL", "http://pdf-api:8000").rstrip("/")


async def _owned_job(job_id: str, user: User, db: AsyncSession) -> PDFJob:
    job = await db.get(PDFJob, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="PDF job not found")
    return job


async def _worker_request(method: str, path: str, **kwargs) -> httpx.Response:
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.request(method, f"{_worker_url()}{path}", **kwargs)
    except (httpx.HTTPError, OSError) as exc:
        raise HTTPException(status_code=503, detail="PDF service unavailable") from exc
    if response.status_code == 503:
        raise HTTPException(status_code=503, detail="PDF service unavailable")
    return response


@router.post("/jobs", response_model=PDFJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_job(
    payload: PDFJobRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> PDFJobResponse:
    await enforce_rate_limit("pdf", user.id, PDF_LIMIT)
    lease = await acquire_active_limit("pdf", user.id, PDF_MAX_ACTIVE)
    try:
        response = await _worker_request("POST", "/scrape_pdf/", json={"pdf_url": str(payload.pdf_url)})
        if response.status_code != 202:
            raise HTTPException(status_code=503, detail="PDF service unavailable")
        try:
            data = response.json()
            job_id = str(data["job_id"])
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=503, detail="PDF service unavailable") from exc
        db.add(PDFJob(job_id=job_id, user_id=user.id))
        await db.commit()
        return PDFJobResponse(job_id=job_id, status="queued")
    finally:
        await lease.release()


@router.get("/jobs/{job_id}", response_model=PDFJobResponse)
async def job_status(
    job_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> PDFJobResponse:
    await _owned_job(job_id, user, db)
    response = await _worker_request("GET", f"/get_pdf/{job_id}")
    if response.status_code == 410:
        raise HTTPException(status_code=410, detail="PDF job expired")
    if response.status_code != 200:
        raise HTTPException(status_code=503, detail="PDF service unavailable")
    try:
        worker_status = response.json()["status"]
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=503, detail="PDF service unavailable") from exc
    mapped = "in-progress" if worker_status in {"started", "deferred", "scheduled", "in_progress"} else worker_status
    if mapped not in {"queued", "in-progress", "finished", "failed"}:
        mapped = "in-progress"
    return PDFJobResponse(job_id=job_id, status=mapped)


@router.get("/jobs/{job_id}/content")
async def job_content(
    job_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
):
    status_response = await job_status(job_id, user, db)
    if status_response.status != "finished":
        raise HTTPException(status_code=409, detail="PDF job is not finished")

    lease = await acquire_active_limit("pdf-content", user.id, PDF_MAX_ACTIVE)
    client = httpx.AsyncClient(timeout=HTTP_TIMEOUT)
    try:
        response = await client.send(
            client.build_request("GET", f"{_worker_url()}/download/{job_id}"), stream=True
        )
    except (httpx.HTTPError, OSError) as exc:
        await client.aclose()
        await lease.release()
        raise HTTPException(status_code=503, detail="PDF service unavailable") from exc
    if response.status_code == 410:
        await response.aclose()
        await client.aclose()
        await lease.release()
        raise HTTPException(status_code=410, detail="PDF job expired")
    if response.status_code == 503:
        await response.aclose()
        await client.aclose()
        await lease.release()
        raise HTTPException(status_code=503, detail="PDF service unavailable")
    if response.status_code != 200:
        await response.aclose()
        await client.aclose()
        await lease.release()
        raise HTTPException(status_code=409, detail="PDF job is not finished")

    async def stream_content():
        try:
            async for chunk in response.aiter_raw():
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()
            await lease.release()

    return StreamingResponse(
        stream_content(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{job_id}.pdf"'},
    )
