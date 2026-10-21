import http.cookiejar
import itertools
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import unquote, urljoin, urlparse
import uuid

import httpx
from seleniumbase import sb_cdp

from pdf_worker.security import validate_public_http_url


WORKER_DIR = Path(__file__).resolve().parent
REPO_DIR = WORKER_DIR.parent
DOWNLOAD_DIR = REPO_DIR / "downloads"
RUNTIME_DIR = WORKER_DIR / "runtime"

DEFAULT_MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024


def max_download_bytes() -> int:
    value = os.getenv("PDF_MAX_DOWNLOAD_BYTES", str(DEFAULT_MAX_DOWNLOAD_BYTES))
    try:
        limit = int(value)
    except ValueError as exc:
        raise ValueError("PDF_MAX_DOWNLOAD_BYTES must be an integer") from exc
    if limit <= 0:
        raise ValueError("PDF_MAX_DOWNLOAD_BYTES must be positive")
    return limit


def egress_proxy_url() -> str | None:
    value = os.getenv("PDF_EGRESS_PROXY_URL", "").strip()
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("PDF_EGRESS_PROXY_URL must be an HTTP(S) proxy URL")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("PDF_EGRESS_PROXY_URL must not include a path, query, or fragment")
    return value


def _chrome_proxy(proxy_url: str | None) -> str | None:
    return urlparse(proxy_url).netloc if proxy_url else None


def _is_probable_pdf_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    query = parsed.query.lower()
    return (
        path.endswith(".pdf")
        or path.endswith("/pdf")
        or path.endswith("/pdf/")
        or "/pdf/" in path
        or "pdf=" in query
        or "format=pdf" in query
        or "download=1" in query
    )


def _cookie_value(cookie, key):
    if isinstance(cookie, dict):
        return cookie.get(key)
    return getattr(cookie, key, None)


def _scoped_cookies(cookies, current_url: str) -> httpx.Cookies:
    """Translate browser cookies without widening domain/path/secure scope."""
    jar = httpx.Cookies()
    default_domain = urlparse(current_url).hostname or ""
    for cookie in cookies:
        name = _cookie_value(cookie, "name")
        value = _cookie_value(cookie, "value")
        if not name or value is None:
            continue
        original_domain = _cookie_value(cookie, "domain") or ""
        domain = original_domain or default_domain
        if not domain:
            continue
        path = _cookie_value(cookie, "path") or "/"
        jar.jar.set_cookie(http.cookiejar.Cookie(
            version=0,
            name=str(name),
            value=str(value),
            port=None,
            port_specified=False,
            domain=domain,
            domain_specified=bool(original_domain),
            domain_initial_dot=original_domain.startswith("."),
            path=path,
            path_specified=True,
            secure=bool(_cookie_value(cookie, "secure")),
            expires=None,
            discard=True,
            comment=None,
            comment_url=None,
            rest={"HttpOnly": None},
            rfc2109=False,
        ))
    return jar


def _safe_filename(filename: str | None, fallback: str | None = None) -> str:
    value = unquote(filename or fallback or "")
    value = re.sub(r'[<>:"/\\|?*]+', "_", Path(value).name).strip(" .")
    if not value:
        value = f"{uuid.uuid4()}.pdf"
    if not value.lower().endswith(".pdf"):
        value += ".pdf"
    return value


def _filename_from_response(response: httpx.Response, url: str) -> str:
    content_disposition = response.headers.get("content-disposition", "")
    match = re.search(r"filename\*=UTF-8''([^;]+)|filename=\"?([^\";]+)", content_disposition)
    filename = (match.group(1) or match.group(2)) if match else None
    return _safe_filename(filename, os.path.basename(urlparse(str(response.url or url)).path))


def _looks_like_pdf(content: bytes, content_type: str = "") -> bool:
    return "pdf" in content_type.lower() or content.lstrip().startswith(b"%PDF")


def _looks_like_html(content: bytes, content_type: str = "") -> bool:
    start = content.lstrip().lower()
    return "html" in content_type.lower() or start.startswith(b"<!doctype html") or start.startswith(b"<html")


class Scraper:
    def __init__(self):
        self.proxy_url = egress_proxy_url()
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        self._profile = tempfile.TemporaryDirectory(prefix="chrome-", dir=RUNTIME_DIR)
        try:
            self.sb = sb_cdp.Chrome(
                uc=True,
                external_pdf=True,
                user_data_dir=self._profile.name,
                browser_args=["--disable-pdf-viewer"],
                proxy=_chrome_proxy(self.proxy_url),
            )
        except Exception:
            self._profile.cleanup()
            raise

    def close(self) -> None:
        try:
            self.sb.quit()
        except Exception:
            pass
        self._profile.cleanup()

    def download_pdf(self, url: str, output_dir: Path | str | None = None) -> str:
        validate_public_http_url(url)
        if output_dir is None:
            output_dir = DOWNLOAD_DIR / f"job-{uuid.uuid4()}"
        try:
            return self._download_pdf(url, output_dir=output_dir)
        except Exception as exc:
            print(f"Error downloading PDF from {url}: {exc}")
            raise
        finally:
            self.close_tabs()

    def _download_pdf(self, url, output_dir=DOWNLOAD_DIR, filename=None):
        if not _is_probable_pdf_url(url):
            url = self.run_scraper(url)
            if not url:
                raise RuntimeError("Could not find a PDF link on the page.")
        try:
            path = self.request_pdf_with_session(url, output_dir=output_dir, filename=filename)
        except (RuntimeError, httpx.HTTPError) as error:
            print(f"HTTP download failed: {error}")
            path = self.download_pdf_with_browser(url, output_dir=output_dir, filename=filename)
        print(f"Downloaded PDF to: {path}")
        return path

    def run_scraper(self, url):
        validate_public_http_url(url)
        self.sb.open(url)
        current_url = self.sb.get_current_url()
        validate_public_http_url(current_url)
        self.sb.sleep(3)
        self.sb.solve_captcha()
        self.sb.sleep(2)
        pdf = self.sb.find_elements("a[href*='pdf'], a[aria-label*='pdf'], a[title*='pdf'], a[content*='pdf'], button[aria-label*='pdf'], button[title*='pdf'], button[content*='pdf'], a:has-text('PDF'), button:has-text('PDF')")
        for pdf_link in pdf:
            for attr in ["href", "content"]:
                try:
                    value = pdf_link.get_attribute(attr)
                    if value and _is_probable_pdf_url(value):
                        value = urljoin(current_url, value)
                        validate_public_http_url(value)
                        return value
                except Exception:
                    continue
        return None

    def _destination(self, output_dir: Path | str, filename: str) -> Path:
        directory = Path(output_dir).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        return directory / _safe_filename(filename)

    def request_pdf_with_session(self, url, output_dir=DOWNLOAD_DIR, filename=None):
        current_url = self.sb.get_current_url()
        absolute_url = urljoin(current_url, url)
        validate_public_http_url(absolute_url)
        headers = {
            "User-Agent": self.sb.evaluate("navigator.userAgent"),
            "Referer": current_url,
            "Accept": "application/pdf,application/octet-stream,*/*;q=0.8",
        }
        cookies = _scoped_cookies(self.sb.get_all_cookies(), current_url)

        for _ in range(10):
            validate_public_http_url(absolute_url)
            with httpx.stream(
                "GET", absolute_url, cookies=cookies, headers=headers,
                follow_redirects=False, timeout=60, proxy=self.proxy_url,
            ) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise RuntimeError("PDF redirect did not include a location")
                    absolute_url = urljoin(absolute_url, location)
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                chunks = response.iter_bytes()
                first_chunk = next(chunks, b"")
                if not _looks_like_pdf(first_chunk, content_type):
                    if _looks_like_html(first_chunk, content_type):
                        snippet = first_chunk[:200].decode(errors="replace").replace("\n", " ").replace("\r", " ")
                        raise RuntimeError(f"URL returned HTML instead of a PDF. Content-Type was: {content_type or 'unknown'}. Snippet: {snippet}")
                    raise RuntimeError(f"URL did not return a PDF. Content-Type was: {content_type or 'unknown'}")
                destination = self._destination(output_dir, filename or _filename_from_response(response, absolute_url))
                if destination.exists():
                    destination = self._destination(output_dir, f"{destination.stem}_{uuid.uuid4().hex[:8]}.pdf")
                part = destination.with_suffix(destination.suffix + ".part")
                written = 0
                try:
                    with part.open("xb") as file:
                        for chunk in itertools.chain((first_chunk,), chunks):
                            written += len(chunk)
                            if written > max_download_bytes():
                                raise RuntimeError(f"PDF exceeds the {max_download_bytes()} byte download limit")
                            file.write(chunk)
                    part.replace(destination)
                except Exception:
                    part.unlink(missing_ok=True)
                    raise
                return str(destination)
        raise RuntimeError("Too many PDF redirects")

    def download_pdf_with_browser(self, url, output_dir=DOWNLOAD_DIR, filename=None, timeout=60):
        current_url = self.sb.get_current_url()
        absolute_url = urljoin(current_url, url)
        validate_public_http_url(absolute_url)
        path = self._destination(output_dir, filename or os.path.basename(urlparse(absolute_url).path))
        if path.exists():
            path = self._destination(output_dir, f"{path.stem}_{uuid.uuid4().hex[:8]}.pdf")
        output_path = path.parent
        before_download = {item.resolve() for item in output_path.glob("*.pdf") if item.is_file()}

        self.sb.loop.run_until_complete(self.sb.page.set_download_path(output_path))
        self.sb.open(absolute_url)
        validate_public_http_url(self.sb.get_current_url())

        deadline = time.time() + timeout
        last_http_attempt = 0
        last_http_error = None
        while time.time() < deadline:
            for partial in output_path.glob("*.crdownload"):
                if partial.stat().st_size > max_download_bytes():
                    partial.unlink(missing_ok=True)
                    raise RuntimeError(f"Browser download exceeds the {max_download_bytes()} byte download limit")
            if time.time() - last_http_attempt >= 3:
                last_http_attempt = time.time()
                try:
                    return self.request_pdf_with_session(absolute_url, output_dir=output_path, filename=path.name)
                except (RuntimeError, httpx.HTTPError) as error:
                    last_http_error = error

            for item in output_path.glob("*.pdf"):
                if not item.is_file() or item.resolve() in before_download or Path(f"{item}.crdownload").exists():
                    continue
                if item.stat().st_size > max_download_bytes():
                    item.unlink(missing_ok=True)
                    raise RuntimeError(f"Browser download exceeds the {max_download_bytes()} byte download limit")
                with item.open("rb") as file:
                    head = file.read(4096)
                if _looks_like_pdf(head):
                    return str(item)
                raise RuntimeError(f"Browser downloaded a file, but it does not look like a PDF: {item}")
            time.sleep(0.5)
        raise TimeoutError(f"Timed out waiting for browser PDF download: {path}. Last HTTP retry error: {last_http_error}")

    def close_tabs(self):
        for tab in self.sb.get_tabs()[1:]:
            self.sb.switch_to_tab(tab)
            self.sb.close_active_tab()
