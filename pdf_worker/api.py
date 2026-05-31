import time
from fastapi import FastAPI
from fastapi.responses import FileResponse
from redis import Redis
from rq import Queue
from rq.job import Job

from pdf_worker.scraper import Scraper

app = FastAPI(title="PDF Worker API")

redis_conn = Redis(host="localhost", port=6379)

queue = Queue("default", connection=redis_conn)

scraper = Scraper()

def fetch_pdf(pdf_urls: str):
    file_path = scraper.download_pdf(pdf_urls)
    return file_path

@app.post("/scrape_pdf/", status_code=202)
def scrape_pdf(pdf_url: str):
    job = queue.enqueue(
        fetch_pdf,
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