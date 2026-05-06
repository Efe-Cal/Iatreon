import os
import random
import asyncio
import re
import tempfile

from playwright.async_api import async_playwright, Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError
from playwright_stealth import Stealth

from urllib.parse import unquote, urlparse
from pypdf import PdfReader

DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)

def _extract_pmc_id(url: str) -> str:
    match = re.search(r"/(?:pmc/)?articles/(PMC)?(\d+)", url, re.IGNORECASE)
    return f"PMC{match.group(2)}" if match else ""

HEADERS = {
    "Accept": "application/pdf,text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Referer": "https://www.google.com",
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
]

class PDFClient:
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
    
    def _special_case_pdf_url(self, url: str) -> str:
        pmc_id = _extract_pmc_id(url)
        if pmc_id:
            return f"https://pmc.ncbi.nlm.nih.gov/articles/{pmc_id}/pdf/"

        book_accession = self._extract_bookshelf_accession(url)
        if book_accession:
            return f"https://www.ncbi.nlm.nih.gov/books/{book_accession}/pdf/Bookshelf_{book_accession}.pdf"

        return url



    def _extract_bookshelf_accession(self, url: str) -> str:
        match = re.search(r"/books/([A-Za-z0-9_]+)/?", url, re.IGNORECASE)
        return match.group(1) if match else ""

    def _extract_doi(self, text: str) -> str:
        match = DOI_PATTERN.search(unquote(text or ""))
        if not match:
            return ""
        return match.group(0).rstrip(").,;?&")

    async def download_pdf(self, page, url: str) -> str:
        print(f"[PDFClient] Downloading PDF from: {url}")
        await Stealth().apply_stealth_async(page)
        
        try:
            async with page.expect_download(timeout=15000) as download_info:
                try:
                    await page.goto(url)
                except PlaywrightError as e:
                    if "Download is starting" not in str(e):
                        return None
        except PlaywrightTimeoutError:
            print(f"[PDFClient] Timeout while waiting for download to start for URL: {url}")
            return None

        download = await download_info.value
        suggested_filename = download.suggested_filename or f"downloaded_{os.urandom(16).hex()}.pdf"
        
        file_path = os.path.join(tempfile.gettempdir(), suggested_filename)
        await download.save_as(file_path)
        print(f"[PDFClient] PDF downloaded to: {file_path}")
        return file_path

    def extract_text_from_pdf(self, pdf_path: str) -> str:
        reader = PdfReader(pdf_path)
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

    async def get_pdf_content(self, url: str):
        print("[PDFClient] Attempting to fetch PDF content from URL:", url)
        async with async_playwright() as p:
            browser = await p.chromium.connect("ws://localhost:3000/")
            context = await browser.new_context(
                accept_downloads=True,
                viewport={"width": 1280, "height": 800},
                user_agent=random.choice(USER_AGENTS),
                locale="tr-TR",
                extra_http_headers=HEADERS,
            )
            
            page = await context.new_page()
            
            pdf_path = await self.download_pdf(page, self._special_case_pdf_url(url))
            
            content = self.extract_text_from_pdf(pdf_path) if pdf_path else None
            
            await context.close()
            await browser.close()
            return content

    async def get_pdf_content_from_doi(self, doi: str):
        pass
    
if __name__ == "__main__":
    import asyncio

    pdf_client = PDFClient()
    pdf_content = asyncio.run(pdf_client.get_pdf_content("https://www.ncbi.nlm.nih.gov/pmc/articles/8407507/"))
    print(f"PDF content saved at: {pdf_content}")
    
# Test URLs
# https://www.ncbi.nlm.nih.gov/pmc/articles/8407507/
# https://link.springer.com/content/pdf/10.1007/s10029-009-0529-7.pdf