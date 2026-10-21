import os
from pathlib import Path
import shutil
import time
import uuid

from rq import get_current_job

from pdf_worker.scraper import DOWNLOAD_DIR, Scraper
from pdf_worker.security import validate_public_http_url


DEFAULT_JOB_DIR_TTL_SECONDS = 60 * 60


def job_dir_ttl_seconds() -> int:
    value = os.getenv("PDF_JOB_DIR_TTL_SECONDS", str(DEFAULT_JOB_DIR_TTL_SECONDS))
    try:
        ttl = int(value)
    except ValueError as exc:
        raise ValueError("PDF_JOB_DIR_TTL_SECONDS must be an integer") from exc
    if ttl <= 0:
        raise ValueError("PDF_JOB_DIR_TTL_SECONDS must be positive")
    return ttl


def cleanup_old_job_dirs(downloads_dir: Path = DOWNLOAD_DIR, *, now: float | None = None) -> None:
    cutoff = (time.time() if now is None else now) - job_dir_ttl_seconds()
    if not downloads_dir.exists():
        return
    for candidate in downloads_dir.glob("job-*"):
        try:
            if candidate.is_dir() and not candidate.is_symlink() and candidate.stat().st_mtime < cutoff:
                shutil.rmtree(candidate)
        except OSError:
            continue


def _job_download_dir() -> Path:
    job = get_current_job()
    job_id = job.id if job is not None else uuid.uuid4().hex
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    directory = DOWNLOAD_DIR / f"job-{job_id}"
    if directory.is_symlink() or directory.is_file():
        directory.unlink()
    elif directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True, exist_ok=False)
    return directory


def fetch_pdf(pdf_urls: str):
    validate_public_http_url(pdf_urls)
    cleanup_old_job_dirs()
    output_dir = _job_download_dir()
    scraper = Scraper()
    try:
        return scraper.download_pdf(pdf_urls, output_dir=output_dir)
    except Exception:
        shutil.rmtree(output_dir, ignore_errors=True)
        raise
    finally:
        scraper.close()
