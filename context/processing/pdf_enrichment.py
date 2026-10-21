import asyncio
import os
import time

from ..models import Article
from .pdf_utils_v2 import PDFClient


DEFAULT_PDF_FETCH_CONCURRENCY = 3
DEFAULT_PDF_RESEARCH_BUDGET_SECONDS = 180


def _positive_int_env(name: str, default: int) -> int:
    value = os.getenv(name, str(default))
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def pdf_fetch_concurrency() -> int:
    return _positive_int_env("PDF_FETCH_CONCURRENCY", DEFAULT_PDF_FETCH_CONCURRENCY)


def pdf_research_budget_seconds() -> int:
    return _positive_int_env("PDF_RESEARCH_BUDGET_SECONDS", DEFAULT_PDF_RESEARCH_BUDGET_SECONDS)


def new_pdf_deadline() -> float:
    return time.monotonic() + pdf_research_budget_seconds()


async def enrich_articles_with_pdfs(
    articles: list[Article],
    pdf_client: PDFClient,
    *,
    deadline: float | None = None,
) -> None:
    """Best-effort PDF enrichment that never discards article metadata."""
    if deadline is None:
        deadline = new_pdf_deadline()

    semaphore = asyncio.Semaphore(pdf_fetch_concurrency())

    async def enrich(article: Article) -> None:
        if article.full_text_available or not article.pdf_url:
            return
        async with semaphore:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            try:
                text = await asyncio.wait_for(pdf_client.get_pdf_content(article.pdf_url), timeout=remaining)
            except Exception:
                return
            if text:
                article.full_text = text
                article.full_text_available = True

    tasks = [asyncio.create_task(enrich(article)) for article in articles if article.pdf_url and not article.full_text_available]
    if not tasks:
        return
    remaining = max(deadline - time.monotonic(), 0)
    try:
        await asyncio.wait(tasks, timeout=remaining)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
