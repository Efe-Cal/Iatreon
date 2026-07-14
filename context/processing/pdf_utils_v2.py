import os
import asyncio
import re
import tempfile

from urllib.parse import unquote, urlparse
from pypdf import PdfReader
import httpx
from liteparse import LiteParse
from local_worker.provider_config import backend_api_url, backend_session


DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
PDF_TEXT_MARKERS = re.compile(r"pdf|download|full\s*text", re.IGNORECASE)
NON_PDF_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".tif", ".tiff"
}

parser = LiteParse(
    ocr_enabled=True,
    output_format="markdown",
)

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

    def _is_probable_non_pdf_asset(self, url: str) -> bool:
        path = urlparse(url).path.lower()
        return any(path.endswith(ext) for ext in NON_PDF_EXTENSIONS)
    
    @staticmethod
    def _extract_pmc_id(url: str) -> str:
        match = re.search(r"/(?:pmc/)?articles/(PMC)?(\d+)", url, re.IGNORECASE)
        return f"PMC{match.group(2)}" if match else ""
    
    def _special_case_pdf_url(self, url: str) -> str:
        pmc_id = self._extract_pmc_id(url)
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

    def _pdf_worker_failed(self, url: str, reason: str) -> None:
        print(f"[PDFClient] PDF worker unavailable for {url}: {reason}")

    async def download_pdf(self, url: str, client: httpx.AsyncClient) -> bytes | None:
        base_url = backend_api_url()
        token = backend_session().get("jwt", "")
        headers = {"Authorization": f"Bearer {token}"}
        try:
            response = await client.post(f"{base_url}/api/v1/pdf/jobs", json={"pdf_url": url}, headers=headers)
            if response.status_code != 202:
                self._pdf_worker_failed(url, f"enqueue returned {response.status_code}")
                return None

            job_id = response.json().get("job_id")
            if not job_id:
                self._pdf_worker_failed(url, "enqueue response did not include a job ID")
                return None

            for _ in range(60):
                status_response = await client.get(f"{base_url}/api/v1/pdf/jobs/{job_id}", headers=headers)
                if status_response.status_code != 200:
                    self._pdf_worker_failed(url, f"status returned {status_response.status_code}")
                    return None

                status_data = status_response.json()
                if status_data.get("status") == "finished":
                    pass
                elif status_data.get("status") == "failed":
                    self._pdf_worker_failed(url, "job failed")
                    return None
                else:
                    await asyncio.sleep(2)
                    continue

                pdf = await client.get(f"{base_url}/api/v1/pdf/jobs/{job_id}/content", headers=headers)
                if pdf.status_code != 200:
                    self._pdf_worker_failed(url, f"download returned {pdf.status_code}")
                    return None
                return pdf.content

            self._pdf_worker_failed(url, "timed out waiting for job")
        except Exception as exc:
            self._pdf_worker_failed(url, str(exc))
        return None

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

    def extract_text_from_pdf_liteparse(self, pdf_path: str) -> str:
        return parser.parse(pdf_path)
         
    
    async def get_pdf_content(self, url: str) -> str:
        async with httpx.AsyncClient(timeout=120) as client:
            try:
                pdf_bytes = await self.download_pdf(self._special_case_pdf_url(url), client)
                if not pdf_bytes:
                    return ""
                
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                    tmp_file.write(pdf_bytes)
                    tmp_path = tmp_file.name

                return self.extract_text_from_pdf_liteparse(tmp_path)
            except Exception as exc:
                print(f"[PDFClient] PDF extraction failed for {url}: {exc}")
                return ""
            finally:
                if 'tmp_path' in locals() and os.path.exists(tmp_path):
                    os.remove(tmp_path)


    
if __name__ == "__main__":
    import asyncio

    pdf_client = PDFClient()
    text = pdf_client.extract_text_from_pdf(r"C:\Users\efeca\Downloads\ehw128.pdf")
    with open("output.txt", "w", encoding="utf-8") as f:
        f.write(text)

# Test URLs
# https://www.ncbi.nlm.nih.gov/pmc/articles/8407507/
# https://link.springer.com/content/pdf/10.1007/s10029-009-0529-7.pdf
