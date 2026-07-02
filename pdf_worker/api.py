import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from redis import Redis, RedisError
from rq import Queue
from rq.exceptions import NoSuchJobError
from rq.job import Job

app = FastAPI(title="PDF Worker API")

redis_conn = Redis(
    host=os.getenv("REDIS_HOST", "redis"),
    port=int(os.getenv("REDIS_PORT", "6379")),
)

queue = Queue("default", connection=redis_conn)

@app.post("/scrape_pdf/", status_code=202)
def scrape_pdf(pdf_url: str):
    try:
        job = queue.enqueue(
            "pdf_worker.jobs.fetch_pdf",
            pdf_url
        )
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="PDF queue unavailable") from exc
    return {"job_id": job.get_id(), "status": "queued"}

@app.get("/get_pdf/{job_id}")
def get_pdf(job_id: str):
    try:
        job = Job.fetch(job_id, connection=redis_conn)
    except NoSuchJobError as exc:
        raise HTTPException(status_code=404, detail="PDF job not found") from exc
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="PDF queue unavailable") from exc
    if job.is_finished:
        return {"job_id": job_id, "status": "finished", "result": job.result}
    elif job.is_failed:
        return {"job_id": job_id, "status": "failed", "error": str(job.exc_info or "")}
    else:
        return {"job_id": job_id, "status": "in_progress"}

@app.get("/download/")
def download_file(file_path: str):
    import os
    if os.path.exists(file_path):
        filename = os.path.basename(file_path)
        return FileResponse(file_path, media_type="application/pdf", filename=filename)
    raise HTTPException(status_code=404, detail="File not found")
