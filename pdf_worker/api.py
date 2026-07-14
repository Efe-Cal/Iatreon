import os
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from redis import Redis, RedisError
from rq import Queue
from rq.exceptions import NoSuchJobError
from rq.job import Job
from pdf_worker.security import resolve_download_path

app = FastAPI(title="PDF Worker API")

redis_conn = Redis(
    host=os.getenv("REDIS_HOST", "redis"),
    port=int(os.getenv("REDIS_PORT", "6379")),
)

queue = Queue("default", connection=redis_conn)


class ScrapePDFRequest(BaseModel):
    pdf_url: str


@app.post("/scrape_pdf/", status_code=202)
def scrape_pdf(request: ScrapePDFRequest):
    try:
        job = queue.enqueue(
            "pdf_worker.jobs.fetch_pdf",
            request.pdf_url
        )
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="PDF queue unavailable") from exc
    return {"job_id": job.get_id(), "status": "queued"}

@app.get("/get_pdf/{job_id}")
def get_pdf(job_id: str):
    try:
        job = Job.fetch(job_id, connection=redis_conn)
    except NoSuchJobError as exc:
        raise HTTPException(status_code=410, detail="PDF job expired") from exc
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="PDF queue unavailable") from exc
    try:
        if job.is_finished:
            return {"job_id": job_id, "status": "finished"}
        if job.is_failed:
            return {"job_id": job_id, "status": "failed"}
        if job.get_status() == "queued":
            return {"job_id": job_id, "status": "queued"}
        return {"job_id": job_id, "status": "in_progress"}
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="PDF queue unavailable") from exc

@app.get("/download/{job_id}")
def download_file(job_id: str):
    try:
        job = Job.fetch(job_id, connection=redis_conn)
    except NoSuchJobError as exc:
        raise HTTPException(status_code=410, detail="PDF job expired") from exc
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="PDF queue unavailable") from exc
    try:
        if not job.is_finished or not isinstance(job.result, str):
            raise HTTPException(status_code=409, detail="PDF job is not finished")
        result = job.result
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="PDF queue unavailable") from exc

    downloads = Path(__file__).resolve().parents[1] / "downloads"
    try:
        candidate = resolve_download_path(result, downloads)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="PDF file not found") from exc
    return FileResponse(candidate, media_type="application/pdf", filename=f"{job_id}.pdf")
