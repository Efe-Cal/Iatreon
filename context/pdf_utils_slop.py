import re
import time
import xml.etree.ElementTree as ET
from io import BytesIO
from typing import Optional
from urllib.parse import unquote, urljoin, urlparse, urlunparse
import os

import requests
from pypdf import PdfReader

from .config import RATE_LIMIT_DELAY
from .unpaywall import get_free_pdf_url

DEFAULT_TIMEOUT = 20
HTML_ACCEPT = "text/html,application/pdf;q=0.9,*/*;q=0.8"
PDF_ACCEPT = "application/pdf,*/*;q=0.8"
PDF_TEXT_MARKERS = re.compile(r"pdf|download|full\s*text", re.IGNORECASE)
DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
BROWSER_VIEWPORT = {"width": 1440, "height": 900}
BROWSER_TIMEOUT_MS = 30000
PLAYWRIGHT_WS_ENDPOINT = os.getenv("PLAYWRIGHT_WS_ENDPOINT", "ws://127.0.0.1:3000/")


class PDFClient:
    def __init__(
        self,
        session: Optional[requests.Session] = None,
        rate_limit_delay: float = RATE_LIMIT_DELAY,
        unpaywall_email: str = "",
        enable_browser_fallback: bool = True,
    ):
        self.session = session or requests.Session()
        self.rate_limit_delay = rate_limit_delay
        self.unpaywall_email = unpaywall_email
        self.enable_browser_fallback = enable_browser_fallback

    def resolve_pdf_url(self, url: str, doi: str = "") -> str:
        return self._resolve_primary_pdf_url(url) or self._resolve_unpaywall_url(doi or self._extract_doi(url))

    def fetch_pdf_bytes(self, url: str, doi: str = "") -> tuple[str, bytes | str]:
        last_url = ""
        for candidate_url in self._candidate_pdf_urls(url, doi):
            last_url = candidate_url

            final_url, pdf_bytes = self._try_fetch_pdf(candidate_url)
            if pdf_bytes:
                return final_url, pdf_bytes

            final_url, pdf_bytes = self._try_fetch_pdf_in_browser(url, candidate_url)
            if pdf_bytes:
                return final_url, pdf_bytes

            if final_url:
                last_url = final_url

        return last_url, "blocked"

    def fetch_pdf_text(self, url: str, doi: str = "") -> str:
        _, pdf_bytes = self.fetch_pdf_bytes(url, doi=doi)
        if pdf_bytes == "blocked":
            return "blocked"
        return self.extract_text_from_pdf(pdf_bytes)

    def extract_text_from_pdf(self, pdf_bytes: bytes) -> str:
        if not pdf_bytes:
            return ""

        try:
            reader = PdfReader(BytesIO(pdf_bytes))
        except Exception:
            return ""

        pages = []
        for page in reader.pages:
            try:
                page_text = page.extract_text() or ""
            except Exception:
                continue

            cleaned = "\n".join(line.strip() for line in page_text.splitlines() if line.strip())
            if cleaned:
                pages.append(cleaned)

        return "\n\n".join(pages)

    def _candidate_pdf_urls(self, url: str, doi: str) -> list[str]:
        candidates = [
            self._resolve_primary_pdf_url(url),
            self._resolve_unpaywall_url(doi or self._extract_doi(url)),
        ]
        return [candidate for candidate in dict.fromkeys(candidates) if candidate]

    def _resolve_primary_pdf_url(self, url: str) -> str:
        normalized_url = self._normalize_source_url(url)
        if not normalized_url:
            return ""

        if self._is_probable_pdf_url(normalized_url):
            return normalized_url

        pmc_pdf_url = self._lookup_pmc_pdf_url(normalized_url)
        if pmc_pdf_url:
            return pmc_pdf_url

        response = self._request(normalized_url, accept=HTML_ACCEPT)
        if response is None:
            return self._special_case_pdf_url(normalized_url)

        final_url = response.url or normalized_url
        if self._response_is_pdf(response):
            return final_url

        return (
            self._discover_pdf_url(response.text, final_url)
            or self._special_case_pdf_url(final_url)
            or self._special_case_pdf_url(normalized_url)
        )

    def _resolve_unpaywall_url(self, doi: str) -> str:
        if not doi:
            return ""
        pdf_url = get_free_pdf_url(doi, email=self.unpaywall_email)
        return self._normalize_source_url(pdf_url) if pdf_url else ""

    def _try_fetch_pdf(self, pdf_url: str) -> tuple[str, bytes]:
        response = self._request(pdf_url, accept=PDF_ACCEPT)
        if response is None:
            return pdf_url, b""

        final_url = response.url or pdf_url
        if self._response_is_pdf(response):
            return final_url, response.content

        discovered_url = self._discover_pdf_url(response.text, final_url)
        if discovered_url and discovered_url != pdf_url:
            return self._try_fetch_pdf(discovered_url)

        return final_url, b""

    def _try_fetch_pdf_in_browser(self, source_url: str, candidate_url: str) -> tuple[str, bytes]:
        if not self.enable_browser_fallback:
            return candidate_url, b""

        playwright_api = self._load_playwright()
        if playwright_api is None:
            return candidate_url, b""

        sync_playwright, playwright_timeout_error = playwright_api

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.connect(PLAYWRIGHT_WS_ENDPOINT, timeout=BROWSER_TIMEOUT_MS)
                try:
                    context = browser.new_context(
                        accept_downloads=True,
                        user_agent=BROWSER_USER_AGENT,
                        viewport=BROWSER_VIEWPORT,
                        locale="en-US",
                    )
                    page = context.new_page()

                    referer = ""
                    if source_url:
                        referer = self._browser_visit(page, source_url)
                        pdf_url, pdf_bytes = self._browser_fetch_candidates(context, page, [candidate_url], referer=referer)
                        if pdf_bytes:
                            return pdf_url, pdf_bytes

                    landing_url = candidate_url if candidate_url != source_url else ""
                    if landing_url:
                        referer = self._browser_visit(page, landing_url) or referer

                    rendered_candidates = self._browser_rendered_candidates(page)
                    pdf_url, pdf_bytes = self._browser_fetch_candidates(
                        context,
                        page,
                        [candidate_url, page.url] + rendered_candidates,
                        referer=referer or page.url,
                    )
                    if pdf_bytes:
                        return pdf_url, pdf_bytes

                    pdf_url, pdf_bytes = self._browser_click_pdf_controls(context, page, playwright_timeout_error)
                    return pdf_url, pdf_bytes
                finally:
                    browser.close()
        except Exception as exc:
            print(
                f"[PDF] Browser fallback failed for {candidate_url} via "
                f"{PLAYWRIGHT_WS_ENDPOINT}: {exc}"
            )
            return candidate_url, b""

    def _browser_fetch_candidates(self, context, page, urls: list[str], referer: str = "") -> tuple[str, bytes]:
        for raw_url in dict.fromkeys(urls):
            normalized_url = self._normalize_candidate_url(raw_url, page.url or referer or raw_url or "")
            if not normalized_url:
                continue

            final_url, pdf_bytes = self._browser_request_pdf(context, normalized_url, referer=referer or page.url)
            if pdf_bytes:
                return final_url, pdf_bytes

        return "", b""

    def _browser_request_pdf(self, context, url: str, referer: str = "") -> tuple[str, bytes]:
        headers = {"Accept": PDF_ACCEPT}
        if referer:
            headers["Referer"] = referer

        try:
            response = context.request.get(url, headers=headers, timeout=BROWSER_TIMEOUT_MS)
        except Exception:
            return url, b""

        try:
            if response.ok and self._header_is_pdf(response.headers):
                return response.url, response.body()
        except Exception:
            return url, b""

        return response.url or url, b""

    def _browser_visit(self, page, url: str) -> str:
        normalized_url = self._normalize_source_url(url)
        if not normalized_url:
            return ""

        try:
            response = page.goto(normalized_url, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT_MS)
            page.wait_for_timeout(1500)
        except Exception:
            return page.url or normalized_url

        if response is not None:
            try:
                if self._header_is_pdf(response.headers):
                    return response.url
            except Exception:
                pass

        return page.url or normalized_url

    def _browser_rendered_candidates(self, page) -> list[str]:
        html_text = ""
        try:
            html_text = page.content()
        except Exception:
            return []

        candidates = self._extract_html_candidates(html_text)
        try:
            link_handles = page.query_selector_all("a[href], link[href], meta[content]")
        except Exception:
            link_handles = []

        for handle in link_handles[:40]:
            try:
                href = handle.get_attribute("href") or handle.get_attribute("content")
            except Exception:
                href = ""
            if href and ("pdf" in href.lower() or "download" in href.lower()):
                candidates.append(href)

        return [candidate for candidate in dict.fromkeys(candidates) if candidate]

    def _browser_click_pdf_controls(self, context, page, playwright_timeout_error) -> tuple[str, bytes]:
        try:
            controls = page.query_selector_all("a, button")
        except Exception:
            return "", b""

        for control in controls[:30]:
            try:
                href = control.get_attribute("href") or ""
                label = " ".join(
                    part for part in [
                        control.inner_text() or "",
                        control.get_attribute("aria-label") or "",
                        control.get_attribute("title") or "",
                    ] if part
                )
            except Exception:
                continue

            if not PDF_TEXT_MARKERS.search(f"{href} {label}"):
                continue

            if href:
                normalized_href = self._normalize_candidate_url(href, page.url)
                if normalized_href:
                    final_url, pdf_bytes = self._browser_request_pdf(context, normalized_href, referer=page.url)
                    if pdf_bytes:
                        return final_url, pdf_bytes

            try:
                with page.expect_download(timeout=5000) as download_info:
                    control.click(timeout=3000)
                download = download_info.value
                download_path = download.path()
                if not download_path:
                    continue
                with open(download_path, "rb") as file_handle:
                    return download.url, file_handle.read()
            except playwright_timeout_error:
                continue
            except Exception:
                continue

        return "", b""

    def _load_playwright(self):
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError:
            return None
        return sync_playwright, PlaywrightTimeoutError

    def _request(self, url: str, accept: str) -> Optional[requests.Response]:
        try:
            response = self.session.get(
                url,
                headers={
                    "User-Agent": BROWSER_USER_AGENT,
                    "Accept": accept,
                },
                allow_redirects=True,
                timeout=DEFAULT_TIMEOUT,
            )
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            print(f"[PDF] Failed to fetch {url}: {exc}")
            return None
        finally:
            time.sleep(self.rate_limit_delay)

    def _discover_pdf_url(self, html_text: str, base_url: str) -> str:
        if not html_text:
            return ""

        for candidate in self._extract_html_candidates(html_text):
            normalized = self._normalize_candidate_url(candidate, base_url)
            if normalized:
                return normalized

        return ""

    def _extract_html_candidates(self, html_text: str) -> list[str]:
        candidates = []

        tag_pattern = re.compile(r"<(?:meta|link)\b[^>]*>", re.IGNORECASE)
        for tag in tag_pattern.findall(html_text):
            lowered = tag.lower()
            if "pdf" not in lowered:
                continue
            for attr_name in ("content", "href"):
                value = self._extract_attr(tag, attr_name)
                if value:
                    candidates.append(value)

        anchor_pattern = re.compile(
            r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
            re.IGNORECASE | re.DOTALL,
        )
        for href, body in anchor_pattern.findall(html_text):
            anchor_text = re.sub(r"<[^>]+>", " ", body)
            if PDF_TEXT_MARKERS.search(f"{href} {anchor_text}"):
                candidates.append(href)

        return candidates

    def _extract_attr(self, tag_text: str, attr_name: str) -> str:
        match = re.search(rf'{attr_name}=[\"\']([^\"\']+)[\"\']', tag_text, re.IGNORECASE)
        return match.group(1).strip() if match else ""

    def _normalize_source_url(self, url: str) -> str:
        normalized = (url or "").strip()
        if not normalized:
            return ""

        if normalized.startswith("//"):
            normalized = f"https:{normalized}"
        elif not re.match(r"^https?://", normalized, re.IGNORECASE):
            return ""

        parsed = urlparse(normalized)
        if not parsed.netloc:
            return ""

        pmc_id = self._extract_pmc_id(normalized)
        if pmc_id and "/pdf" not in parsed.path.lower():
            return f"https://pmc.ncbi.nlm.nih.gov/articles/{pmc_id}/"

        cleaned = parsed._replace(fragment="", path=parsed.path or "/")
        return urlunparse(cleaned)

    def _normalize_candidate_url(self, url: str, base_url: str) -> str:
        if not url:
            return ""
        normalized = self._normalize_source_url(urljoin(base_url or "", url.strip()))
        if not normalized:
            return ""
        return normalized if self._is_probable_pdf_url(normalized) else self._special_case_pdf_url(normalized)

    def _lookup_pmc_pdf_url(self, url: str) -> str:
        pmc_id = self._extract_pmc_id(url)
        if not pmc_id:
            return ""

        response = self._request(
            f"https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id={pmc_id}",
            accept="application/xml,text/xml;q=0.9,*/*;q=0.8",
        )
        if response is None:
            return ""

        try:
            root = ET.fromstring(response.text)
        except ET.ParseError:
            return ""

        for link in root.findall(".//link"):
            if (link.get("format") or "").lower() != "pdf":
                continue

            href = (link.get("href") or "").strip()
            if href:
                return self._normalize_pmc_oa_url(href)

        return ""

    def _special_case_pdf_url(self, url: str) -> str:
        pmc_id = self._extract_pmc_id(url)
        if pmc_id:
            return f"https://pmc.ncbi.nlm.nih.gov/articles/{pmc_id}/pdf/"

        book_accession = self._extract_bookshelf_accession(url)
        if book_accession:
            return f"https://www.ncbi.nlm.nih.gov/books/{book_accession}/pdf/Bookshelf_{book_accession}.pdf"

        return ""

    def _normalize_pmc_oa_url(self, url: str) -> str:
        normalized = (url or "").strip()
        if normalized.startswith("ftp://ftp.ncbi.nlm.nih.gov/"):
            normalized = normalized.replace("ftp://ftp.ncbi.nlm.nih.gov/", "https://ftp.ncbi.nlm.nih.gov/", 1)
        return self._normalize_source_url(normalized)

    def _extract_pmc_id(self, url: str) -> str:
        match = re.search(r"/(?:pmc/)?articles/(PMC)?(\d+)", url, re.IGNORECASE)
        return f"PMC{match.group(2)}" if match else ""

    def _extract_bookshelf_accession(self, url: str) -> str:
        match = re.search(r"/books/([A-Za-z0-9_]+)/?", url, re.IGNORECASE)
        return match.group(1) if match else ""

    def _extract_doi(self, text: str) -> str:
        match = DOI_PATTERN.search(unquote(text or ""))
        if not match:
            return ""
        return match.group(0).rstrip(").,;?&")

    def _response_is_pdf(self, response: requests.Response) -> bool:
        content_type = response.headers.get("Content-Type", "").lower()
        return "pdf" in content_type or response.content.startswith(b"%PDF")

    def _header_is_pdf(self, headers) -> bool:
        content_type = (headers.get("content-type") or headers.get("Content-Type") or "").lower()
        return "pdf" in content_type

    def _is_probable_pdf_url(self, url: str) -> bool:
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


if __name__ == "__main__":
    client = PDFClient()
    test_urls = [
        ("https://www.ncbi.nlm.nih.gov/pmc/articles/8407507", "10.1002/14651858.cd001785"),
        ("https://www.nejm.org/doi/pdf/10.1056/NEJMoa040093?articleTools=true", "10.1056/NEJMoa040093"),
    ]
    for url, doi in test_urls:
        pdf_url = client.resolve_pdf_url(url, doi=doi)
        print(f"Source URL: {url}")
        print(f"Resolved PDF URL: {pdf_url}")
        print(f"Fetch result: {client.fetch_pdf_text(url, doi=doi)}")
        print("-" * 80)
