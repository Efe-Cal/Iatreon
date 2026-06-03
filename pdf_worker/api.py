import os
from fastapi import FastAPI
from fastapi.responses import FileResponse
from redis import Redis
from rq import Queue
from rq.job import Job

app = FastAPI(title="PDF Worker API")

redis_conn = Redis(
    host=os.getenv("REDIS_HOST", "redis"),
    port=int(os.getenv("REDIS_PORT", "6379")),
)

queue = Queue("default", connection=redis_conn)

@app.post("/scrape_pdf/", status_code=202)
def scrape_pdf(pdf_url: str):
    job = queue.enqueue(
        "pdf_worker.jobs.fetch_pdf",
        pdf_url
    )
    return {"job_id": job.get_id(), "status": "queued"}

@app.get("/get_pdf/{job_id}")
def get_pdf(job_id: str):
    job = Job.fetch(job_id, connection=redis_conn)
    if job.is_finished:
        return {"job_id": job_id, "status": "finished", "result": job.result}
    elif job.is_failed:
        return {"job_id": job_id, "status": "failed"}
    else:
        return {"job_id": job_id, "status": "in_progress"}

@app.get("/download/")
def download_file(file_path: str):
    import os
    if os.path.exists(file_path):
        filename = os.path.basename(file_path)
        return FileResponse(file_path, media_type="application/pdf", filename=filename)
    return {"error": "File not found"}