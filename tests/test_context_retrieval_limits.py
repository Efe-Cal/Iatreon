import asyncio
import time

import pytest

from context.models import Article
from context.processing.pdf_enrichment import enrich_articles_with_pdfs
from context.sources import get_ncbi_books


def test_bookshelf_url_normalization_rejects_untrusted_results():
    normalize = get_ncbi_books.normalize_bookshelf_url
    assert normalize("https://ncbi.nlm.nih.gov/books/NBK123/chapter-1/") == "https://www.ncbi.nlm.nih.gov/books/NBK123/"
    for value in (
        "http://www.ncbi.nlm.nih.gov/books/NBK123/",
        "https://ncbi.nlm.nih.gov.evil.test/books/NBK123/",
        "https://www.ncbi.nlm.nih.gov/books/NBK%2F123/",
        "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1/",
    ):
        with pytest.raises(ValueError):
            normalize(value)


class _Response:
    def __init__(self, location=None):
        self.is_redirect = location is not None
        self.headers = {"Location": location} if location else {}


def test_bookshelf_redirects_are_validated_and_bounded(monkeypatch):
    client = get_ncbi_books.BookshelfClient.__new__(get_ncbi_books.BookshelfClient)
    calls = []

    def evil_redirect(url, **kwargs):
        calls.append((url, kwargs))
        return _Response("https://example.test/not-books")

    monkeypatch.setattr(get_ncbi_books, "ncbi_get", evil_redirect)
    with pytest.raises(ValueError):
        client._get_bookshelf_response("https://www.ncbi.nlm.nih.gov/books/NBK123/", {})
    assert calls[0][1]["allow_redirects"] is False

    calls.clear()
    monkeypatch.setattr(
        get_ncbi_books,
        "ncbi_get",
        lambda *args, **kwargs: (calls.append(args[0]) or _Response("/books/NBK123/")),
    )
    with pytest.raises(ValueError, match="redirect limit"):
        client._get_bookshelf_response("https://www.ncbi.nlm.nih.gov/books/NBK123/", {})
    assert len(calls) == 6


class _PDFClient:
    def __init__(self, delay=0.01):
        self.delay = delay
        self.active = 0
        self.max_active = 0
        self.cancelled = 0

    async def get_pdf_content(self, url):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(self.delay)
            return f"text for {url}"
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        finally:
            self.active -= 1


def test_pdf_enrichment_is_bounded_and_concurrent(monkeypatch):
    monkeypatch.setenv("PDF_FETCH_CONCURRENCY", "3")
    client = _PDFClient()
    articles = [Article(pdf_url=f"https://example.com/{index}.pdf") for index in range(7)]
    asyncio.run(enrich_articles_with_pdfs(articles, client, deadline=time.monotonic() + 1))
    assert client.max_active == 3
    assert all(article.full_text_available for article in articles)


def test_pdf_enrichment_cancels_pending_tasks_at_deadline(monkeypatch):
    monkeypatch.setenv("PDF_FETCH_CONCURRENCY", "3")
    client = _PDFClient(delay=10)
    articles = [Article(pdf_url=f"https://example.com/{index}.pdf") for index in range(5)]
    asyncio.run(enrich_articles_with_pdfs(articles, client, deadline=time.monotonic() + 0.01))
    assert client.cancelled == 3
    assert not any(article.full_text_available for article in articles)


def test_pdf_enrichment_cancels_children_with_parent(monkeypatch):
    monkeypatch.setenv("PDF_FETCH_CONCURRENCY", "1")
    client = _PDFClient(delay=10)
    articles = [Article(pdf_url=f"https://example.com/{index}.pdf") for index in range(3)]

    async def cancel_research():
        task = asyncio.create_task(enrich_articles_with_pdfs(articles, client))
        try:
            while not client.active:
                await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert client.active == 0
            assert client.cancelled == 1
        finally:
            # Clean up leaked children even when testing the broken version.
            children = asyncio.all_tasks() - {asyncio.current_task()}
            for child in children:
                child.cancel()
            await asyncio.gather(*children, return_exceptions=True)

    asyncio.run(cancel_research())
