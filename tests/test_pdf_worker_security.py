import socket
from pathlib import Path
import importlib
import os

import pytest


@pytest.fixture
def scraper_module():
    return importlib.import_module("pdf_worker.scraper")


def test_url_validation_rejects_schemes_credentials_and_private_hosts(monkeypatch):
    from pdf_worker.security import validate_public_http_url

    monkeypatch.setattr(socket, "getaddrinfo", lambda *args: [(socket.AF_INET, 0, 0, "", ("93.184.216.34", 0))])
    assert validate_public_http_url("https://example.com/article.pdf")
    with pytest.raises(ValueError):
        validate_public_http_url("file:///etc/passwd")
    with pytest.raises(ValueError):
        validate_public_http_url("https://user:pass@example.com/a.pdf")
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args: [(socket.AF_INET, 0, 0, "", ("127.0.0.1", 0))])
    with pytest.raises(ValueError):
        validate_public_http_url("http://localhost/a.pdf")


def test_internal_download_rejects_paths_outside_downloads(monkeypatch, tmp_path):
    from pdf_worker.security import resolve_download_path

    downloads = tmp_path / "downloads"
    downloads.mkdir()
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF")
    with pytest.raises(FileNotFoundError):
        resolve_download_path(str(outside), downloads)

    traversal = downloads / ".." / "outside.pdf"
    with pytest.raises(FileNotFoundError):
        resolve_download_path(str(traversal), downloads)


def test_internal_download_rejects_symlink_escape(tmp_path):
    from pdf_worker.security import resolve_download_path

    downloads = tmp_path / "downloads"
    downloads.mkdir()
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF")
    link = downloads / "linked.pdf"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable")
    with pytest.raises(FileNotFoundError):
        resolve_download_path(str(link), downloads)


def test_scoped_cookies_preserve_domain_path_and_secure(scraper_module):
    jar = scraper_module._scoped_cookies(
        [{"name": "session", "value": "secret", "domain": ".example.com", "path": "/members", "secure": True}],
        "https://example.com/members/report",
    )
    cookie = next(iter(jar.jar))
    assert cookie.domain == ".example.com"
    assert cookie.domain_initial_dot
    assert cookie.path == "/members"
    assert cookie.secure


def test_proxy_url_requires_a_proxy_origin(monkeypatch, scraper_module):
    monkeypatch.setenv("PDF_EGRESS_PROXY_URL", "http://squid:3128")
    assert scraper_module.egress_proxy_url() == "http://squid:3128"
    assert scraper_module._chrome_proxy(scraper_module.egress_proxy_url()) == "squid:3128"
    monkeypatch.setenv("PDF_EGRESS_PROXY_URL", "squid:3128/path")
    with pytest.raises(ValueError):
        scraper_module.egress_proxy_url()


class _FakeResponse:
    def __init__(self, chunks, headers=None, url="https://example.com/article.pdf"):
        self._chunks = chunks
        self.headers = headers or {"content-type": "application/pdf"}
        self.url = url
        self.is_redirect = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self):
        return None

    def iter_bytes(self):
        yield from self._chunks


class _FakeBrowser:
    def get_current_url(self):
        return "https://example.com/article"

    def evaluate(self, script):
        assert script == "navigator.userAgent"
        return "test-agent"

    def get_all_cookies(self):
        return []


class _FakeDownloadLoop:
    def run_until_complete(self, value):
        return value


class _FakeDownloadBrowser(_FakeBrowser):
    def __init__(self):
        self.loop = _FakeDownloadLoop()
        self.page = type("Page", (), {"set_download_path": lambda self, path: None})()

    def open(self, url):
        return None


def _bare_scraper(scraper_module):
    scraper = scraper_module.Scraper.__new__(scraper_module.Scraper)
    scraper.proxy_url = "http://squid:3128"
    scraper.sb = _FakeBrowser()
    return scraper


def test_http_download_streams_to_part_then_renames(monkeypatch, tmp_path, scraper_module):
    monkeypatch.setattr(scraper_module, "validate_public_http_url", lambda url: url)
    calls = []

    def stream(*args, **kwargs):
        calls.append(kwargs)
        return _FakeResponse([b"%PDF-1.7\n", b"content"])

    monkeypatch.setattr(scraper_module.httpx, "stream", stream)
    result = _bare_scraper(scraper_module).request_pdf_with_session(
        "https://example.com/article.pdf", output_dir=tmp_path,
    )
    destination = Path(result)
    assert destination.read_bytes() == b"%PDF-1.7\ncontent"
    assert not list(tmp_path.glob("*.part"))
    assert calls[0]["proxy"] == "http://squid:3128"


def test_http_download_removes_part_when_over_limit(monkeypatch, tmp_path, scraper_module):
    monkeypatch.setenv("PDF_MAX_DOWNLOAD_BYTES", "8")
    monkeypatch.setattr(scraper_module, "validate_public_http_url", lambda url: url)
    monkeypatch.setattr(
        scraper_module.httpx,
        "stream",
        lambda *args, **kwargs: _FakeResponse([b"%PDF-1.7\n", b"too-large"]),
    )
    with pytest.raises(RuntimeError, match="download limit"):
        _bare_scraper(scraper_module).request_pdf_with_session(
            "https://example.com/article.pdf", output_dir=tmp_path,
        )
    assert not list(tmp_path.iterdir())


def test_browser_download_removes_any_oversize_partial(monkeypatch, tmp_path, scraper_module):
    monkeypatch.setenv("PDF_MAX_DOWNLOAD_BYTES", "8")
    monkeypatch.setattr(scraper_module, "validate_public_http_url", lambda url: url)
    (tmp_path / "content-disposition-name.pdf.crdownload").write_bytes(b"x" * 9)
    scraper = _bare_scraper(scraper_module)
    scraper.sb = _FakeDownloadBrowser()
    with pytest.raises(RuntimeError, match="download limit"):
        scraper.download_pdf_with_browser("https://example.com/article.pdf", output_dir=tmp_path)
    assert not (tmp_path / "content-disposition-name.pdf.crdownload").exists()


def test_cleanup_removes_only_expired_job_directories(monkeypatch, tmp_path):
    from pdf_worker import jobs

    monkeypatch.setenv("PDF_JOB_DIR_TTL_SECONDS", "60")
    stale = tmp_path / "job-stale"
    stale.mkdir()
    current = tmp_path / "job-current"
    current.mkdir()
    unrelated = tmp_path / "other"
    unrelated.mkdir()
    os.utime(stale, (900, 900))
    os.utime(current, (999, 999))
    jobs.cleanup_old_job_dirs(tmp_path, now=1000)
    assert not stale.exists()
    assert current.exists()
    assert unrelated.exists()


def test_job_retry_reclaims_its_stale_directory(monkeypatch, tmp_path):
    from pdf_worker import jobs

    stale = tmp_path / "job-retry"
    stale.mkdir()
    (stale / "partial.pdf.part").write_bytes(b"partial")
    monkeypatch.setattr(jobs, "DOWNLOAD_DIR", tmp_path)
    monkeypatch.setattr(jobs, "get_current_job", lambda: type("Job", (), {"id": "retry"})())

    directory = jobs._job_download_dir()

    assert directory == stale
    assert list(directory.iterdir()) == []


def test_enqueue_sets_job_timeout_and_result_ttls(monkeypatch):
    from pdf_worker import api

    received = {}

    class Queue:
        def enqueue(self, *args, **kwargs):
            received["args"] = args
            received["kwargs"] = kwargs
            return type("Job", (), {"get_id": lambda self: "job-1"})()

    monkeypatch.setattr(api, "queue", Queue())
    assert api.scrape_pdf(api.ScrapePDFRequest(pdf_url="https://example.com/a.pdf")) == {"job_id": "job-1", "status": "queued"}
    assert received["kwargs"] == {"job_timeout": 180, "result_ttl": 3600, "failure_ttl": 3600}
