import os
from pathlib import Path
import re
import time
from urllib.parse import urlparse, urljoin, unquote
import uuid
from seleniumbase import sb_cdp
import httpx

BASE_DIR = os.path.dirname(os.getcwd())
PROFILE_DIR = os.path.join(BASE_DIR, "chrome_profile")
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
os.makedirs(PROFILE_DIR, exist_ok=True)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

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

def _filename_from_response(response: httpx.Response, url: str) -> str:
        content_disposition = response.headers.get("content-disposition", "")
        match = re.search(r"filename\*=UTF-8''([^;]+)|filename=\"?([^\";]+)", content_disposition)
        if match:
            filename = unquote(match.group(1) or match.group(2))
        else:
            filename = unquote(os.path.basename(urlparse(str(response.url or url)).path))

        filename = re.sub(r'[<>:"/\\|?*]+', "_", filename).strip(" .")
        if not filename:
            filename = f"{uuid.uuid4()}.pdf"
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"
        return filename

def _looks_like_pdf(content: bytes, content_type: str = "") -> bool:
        return "pdf" in content_type.lower() or content.lstrip().startswith(b"%PDF")

def _looks_like_html(content: bytes, content_type: str = "") -> bool:
        start = content.lstrip().lower()
        return "html" in content_type.lower() or start.startswith(b"<!doctype html") or start.startswith(b"<html")

class Scraper:
    def __init__(self):
        print(f"Loading persistent session from: {PROFILE_DIR}")
        self.sb = sb_cdp.Chrome(uc=True, external_pdf=True, user_data_dir=PROFILE_DIR, chromium_arg="--disable-pdf-viewer")
    
    def download_pdfs(self, urls: list) -> list:
        paths = []
        try:
            for url in urls:
                paths.append(self._download_pdf(url))
            return paths
        finally:
            self.close_tabs()
    
    def _download_pdf(self, url, output_dir=DOWNLOAD_DIR, filename=None):
        if  not _is_probable_pdf_url(url):
            url = self.run_scraper(url)
            if not url:
                raise RuntimeError("Could not find a PDF link on the page.")

        try:
            path = self.request_pdf_with_session(url, output_dir=output_dir, filename=filename)
        except (RuntimeError, httpx.HTTPError) as error:
            print(f"HTTP download failed: {error}")
            print("Falling back to browser download...")
            path = self.download_pdf_with_browser(url, output_dir=output_dir, filename=filename)
        print(f"Downloaded PDF to: {path}")
        return path

    def run_scraper(self, url):
        self.sb.open(url)
        self.sb.sleep(3)
        
        self.sb.solve_captcha()
        self.sb.sleep(2)
        
        pdf = self.sb.find_elements("a[href*='pdf'], a[aria-label*='pdf'], a[title*='pdf'], a[content*='pdf'], button[aria-label*='pdf'], button[title*='pdf'], button[content*='pdf'], a:has-text('PDF'), button:has-text('PDF')")
        for pdf_link in pdf:
            for attr in ["href", "content"]:
                try:
                    value = pdf_link.get_attribute(attr)
                    print(f"Checking attribute '{attr}': {value}")
                    if value and _is_probable_pdf_url(value):
                        print(f"Found PDF URL: {value}")
                        return value
                except Exception as e:
                    import traceback
                    print(f"Error while processing attribute '{attr}': {e}")
                    traceback.print_exc()
                    continue

    def request_pdf_with_session(self, url, output_dir=DOWNLOAD_DIR, filename=None):
        os.makedirs(output_dir, exist_ok=True)

        current_url = self.sb.get_current_url()
        absolute_url = urljoin(current_url, url)
        user_agent = self.sb.evaluate("navigator.userAgent")

        headers = {
            "User-Agent": user_agent,
            "Referer": current_url,
            "Accept": "application/pdf,application/octet-stream,*/*;q=0.8",
        }

        cookies = self.sb.get_all_cookies()
        httpx_cookies = {
            _cookie_value(cookie, "name"): _cookie_value(cookie, "value")
            for cookie in cookies
            if _cookie_value(cookie, "name")
        }

        print(f"Absolute URL to download: {absolute_url}")
        response = httpx.get(
            absolute_url,
            cookies=httpx_cookies,
            headers=headers,
            follow_redirects=True,
            timeout=60,
        )
        response.raise_for_status()

        content_type = response.headers.get("content-type", "").lower()
        if not _looks_like_pdf(response.content, content_type):
            if _looks_like_html(response.content, content_type):
                snippet = response.text[:200].replace("\n", " ").replace("\r", " ")
                raise RuntimeError(
                    f"URL returned HTML instead of a PDF. Content-Type was: "
                    f"{content_type or 'unknown'}. Snippet: {snippet}"
                )
            raise RuntimeError(
                f"URL did not return a PDF. Content-Type was: {content_type or 'unknown'}"
            )

        filename = filename or _filename_from_response(response, absolute_url)
        path = os.path.join(output_dir, filename)
        with open(path, "wb") as file:
            file.write(response.content)

        return path

    def download_pdf_with_browser(self, url, output_dir=DOWNLOAD_DIR, filename=None, timeout=60):
        os.makedirs(output_dir, exist_ok=True)

        current_url = self.sb.get_current_url()
        absolute_url = urljoin(current_url, url)
        filename = filename or unquote(os.path.basename(urlparse(absolute_url).path)) or f"{uuid.uuid4()}.pdf"
        filename = re.sub(r'[<>:"/\\|?*]+', "_", filename).strip(" .")
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"

        path = os.path.join(output_dir, filename)
        partial_path = f"{path}.crdownload"
        if os.path.exists(path):
            base, ext = os.path.splitext(filename)
            filename = f"{base}_{uuid.uuid4().hex[:8]}{ext}"
            path = os.path.join(output_dir, filename)
            partial_path = f"{path}.crdownload"

        output_path = Path(output_dir).resolve()
        before_download = {
            item.resolve()
            for item in output_path.glob("*.pdf")
            if item.is_file()
        }

        self.sb.loop.run_until_complete(self.sb.page.set_download_path(output_path))
        self.sb.open(absolute_url)

        deadline = time.time() + timeout
        last_http_attempt = 0
        last_http_error = None
        while time.time() < deadline:
            if time.time() - last_http_attempt >= 3:
                last_http_attempt = time.time()
                try:
                    return self.request_pdf_with_session(
                        absolute_url,
                        output_dir=str(output_path),
                        filename=filename,
                    )
                except (RuntimeError, httpx.HTTPError) as error:
                    last_http_error = error

            if os.path.exists(path) and not os.path.exists(partial_path):
                with open(path, "rb") as file:
                    head = file.read(4096)
                if _looks_like_pdf(head):
                    return path
                raise RuntimeError(f"Browser downloaded a file, but it does not look like a PDF: {path}")

            completed_downloads = [
                item
                for item in output_path.glob("*.pdf")
                if item.is_file()
                and item.resolve() not in before_download
                and not Path(f"{item}.crdownload").exists()
            ]
            for item in completed_downloads:
                with open(item, "rb") as file:
                    head = file.read(4096)
                if _looks_like_pdf(head):
                    return str(item)
            time.sleep(0.5)

        raise TimeoutError(
            f"Timed out waiting for browser PDF download: {path}. "
            f"Last HTTP retry error: {last_http_error}"
        )
        
    def close_tabs(self):
        self.sb.get_tabs()
        for tab in self.sb.get_tabs()[1:]:
            self.sb.switch_to_tab(tab)
            self.sb.close_active_tab()

if __name__ == "__main__":
    scraper = Scraper()
    try:
        path = scraper._download_pdf("https://www.ncbi.nlm.nih.gov/pmc/articles/8407507/")
    finally:
        scraper.close_tabs()
