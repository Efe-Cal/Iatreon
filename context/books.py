import time
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from io import BytesIO
import re
from typing import Optional

import requests

from .config import NCBI_API_KEY, NCBI_BASE, RATE_LIMIT_DELAY
from .models import Book


class NCBIBooksClient:
    def search_books(self, query: str, max_results: int = 5) -> list[Book]:
        print(f"\n[NCBI Books] Searching: '{query}'")

        params = {
            "db": "books",
            "term": query,
            "field": "title",
            "sort": "relevance",
            "retmax": min(max(max_results * 10, 20), 75),
            "retmode": "json",
        }
        if NCBI_API_KEY:
            params["api_key"] = NCBI_API_KEY

        r = requests.get(f"{NCBI_BASE}/esearch.fcgi", params=params)
        r.raise_for_status()
        ids = r.json()["esearchresult"]["idlist"]
        time.sleep(RATE_LIMIT_DELAY)

        if not ids:
            print("[NCBI Books] No results found")
            return []

        candidate_ids = ids[:max_results]
        return self.fetch_book_sections(candidate_ids)[:max_results]

    def fetch_book_sections(self, book_ids: list[str]) -> list[Book]:
        if not book_ids:
            return []

        book_ids = list(dict.fromkeys(book_ids))

        params = {
            "db": "books",
            "id": ",".join(book_ids),
            "retmode": "json",
        }
        if NCBI_API_KEY:
            params["api_key"] = NCBI_API_KEY

        r = requests.get(f"{NCBI_BASE}/esummary.fcgi", params=params)
        r.raise_for_status()
        time.sleep(RATE_LIMIT_DELAY)

        summary = r.json().get("result", {})
        sections = []
        seen_urls = set()

        for book_id in summary.get("uids", []):
            record = summary.get(book_id)
            if not record:
                continue

            section = self._fetch_book_section_from_summary(record)
            if section:
                dedupe_key = section.pdf_url or section.url
                if dedupe_key and dedupe_key in seen_urls:
                    continue
                if dedupe_key:
                    seen_urls.add(dedupe_key)
                sections.append(section)

        return sections

    def _fetch_book_section_from_summary(self, record: dict) -> Optional[Book]:
        page_accession = (
            record.get("chapteraccessionid")
            or record.get("accessionid")
            or self._extract_parent_book_accession(record.get("bookinfo", ""))
        )
        if not page_accession:
            return None

        page_url = self._build_book_page_url(page_accession)
        target_section_id = self._extract_section_id(record.get("rid", ""))

        try:
            r = requests.get(
                page_url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "text/html,application/xhtml+xml",
                },
            )
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"[NCBI Books] Failed to fetch {page_accession}: {e}")
            return None

        time.sleep(RATE_LIMIT_DELAY)
        text = self._extract_text_from_book_html(r.text, target_section_id=target_section_id)
        if not text:
            return None

        source_title = self._extract_parent_book_title(record.get("bookinfo", ""))
        source = f"NCBI Bookshelf - {source_title}" if source_title else "NCBI Bookshelf"
        pdf_url = self._discover_pdf_url(r.text, page_accession)
        pdf_text = self._fetch_pdf_text(pdf_url) if pdf_url else ""
        text_source = "html"

        return Book(
            accession_id=page_accession,
            title=record.get("title") or "Section",
            source=source,
            text_source=text_source,
            text=text,
            page_url=page_url,
            url=page_url,
            pdf_url=pdf_url,
            pdf_url_found=bool(pdf_url),
            pdf_text=pdf_text,
            pdf_text_extracted=bool(pdf_text),
            full_text_available=bool(text or pdf_text),
        )

    def _extract_section_id(self, rid: str) -> str:
        if "/" not in rid:
            return ""
        return rid.split("/", 1)[1]

    def _build_book_page_url(self, accession_id: str) -> str:
        return f"https://www.ncbi.nlm.nih.gov/books/{accession_id}/"

    def _build_pdf_url(self, accession_id: str) -> str:
        accession_id = accession_id.strip("/")
        return f"https://www.ncbi.nlm.nih.gov/books/{accession_id}/pdf/Bookshelf_{accession_id}.pdf"

    def _fetch_pdf_text(self, pdf_url: str) -> str:
        if not pdf_url:
            return ""

        try:
            r = requests.get(
                pdf_url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/pdf,*/*",
                },
            )
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"[NCBI Books] Failed to fetch PDF {pdf_url}: {e}")
            return ""

        time.sleep(RATE_LIMIT_DELAY)

        content_type = r.headers.get("Content-Type", "").lower()
        if "pdf" not in content_type and not r.content.startswith(b"%PDF"):
            return ""

        text = self._extract_text_from_pdf(r.content)
        if text:
            return text

        print(f"[NCBI Books] PDF fetched but text extraction failed: {pdf_url}")
        return ""

    def _discover_pdf_url(self, html_text: str, page_accession: str) -> str:
        if not html_text:
            return ""

        match = re.search(r'href=["\']([^"\']+/pdf/Bookshelf_[^"\']+\.pdf)["\']', html_text, re.IGNORECASE)
        if match:
            return self._normalize_pdf_url(match.group(1))

        if page_accession:
            candidate = self._build_pdf_url(page_accession)
            if candidate in html_text:
                return candidate
        print(f"[NCBI Books] No PDF link found in HTML for accession {page_accession}")
        return ""

    def _normalize_pdf_url(self, pdf_url: str) -> str:
        if pdf_url.startswith("//"):
            return f"https:{pdf_url}"
        if pdf_url.startswith("/"):
            return f"https://www.ncbi.nlm.nih.gov{pdf_url}"
        return pdf_url

    def _extract_text_from_pdf(self, pdf_bytes: bytes) -> str:
        for reader_factory in self._pdf_reader_factories():
            text = reader_factory(pdf_bytes)
            if text:
                return text
        return ""

    def _pdf_reader_factories(self):
        factories = []

        from pypdf import PdfReader

        def extract_with_pypdf(pdf_bytes: bytes) -> str:
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

        factories.append(extract_with_pypdf)
        
        return factories

    def _extract_parent_book_accession(self, bookinfo_xml: str) -> str:
        if not bookinfo_xml:
            return ""

        try:
            root = ET.fromstring(bookinfo_xml)
        except ET.ParseError:
            return ""

        parent = root.find(".//Parent")
        if parent is None:
            return ""

        for element in parent.iter():
            if "accession" in element.tag.lower() and element.text:
                return element.text.strip()

        return ""

    def _parse_book_xml(self, xml_text: str) -> list[Book]:
        sections = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return []

        for book in root.findall(".//book-part") or root.findall(".//sec"):
            title_elem = book.find(".//title")
            title = "".join(title_elem.itertext()).strip() if title_elem is not None else "Section"

            paragraphs = []
            for p in book.findall(".//p"):
                text = "".join(p.itertext()).strip()
                if text:
                    paragraphs.append(text)

            if paragraphs:
                sections.append(
                    Book(
                        title=title,
                        text="\n".join(paragraphs),
                        source="NCBI Bookshelf",
                        text_source="xml",
                        full_text_available=True,
                    )
                )

        return sections

    def _extract_parent_book_title(self, bookinfo_xml: str) -> str:
        if not bookinfo_xml:
            return ""

        try:
            root = ET.fromstring(bookinfo_xml)
        except ET.ParseError:
            return ""

        parent = root.find(".//Parent/Title")
        if parent is None or not parent.text:
            return ""
        return parent.text.strip()

    def _extract_text_from_book_html(self, html_text: str, target_section_id: str = "") -> str:
        parser = _BookshelfHTMLParser(target_section_id=target_section_id)
        parser.feed(html_text)
        parser.close()
        if parser.paragraphs:
            return "\n".join(parser.paragraphs)

        if target_section_id:
            return self._extract_section_text_with_xml_parser(html_text, target_section_id)

        return ""

    def _extract_section_text_with_xml_parser(self, html_text: str, target_section_id: str) -> str:
        try:
            root = ET.fromstring(html_text)
        except ET.ParseError:
            return ""

        section = root.find(f".//*[@id='{target_section_id}']")
        if section is None:
            return ""

        parts = []
        for text in section.itertext():
            cleaned = " ".join(text.split())
            if cleaned:
                parts.append(cleaned)

        return " ".join(parts)


class _BookshelfHTMLParser(HTMLParser):
    def __init__(self, target_section_id: str = ""):
        super().__init__(convert_charrefs=True)
        self.target_section_id = target_section_id
        self.in_body_content = False
        self.body_depth = 0
        self.capture_depth = 0
        self.in_paragraph = False
        self.current_paragraph = []
        self.paragraphs = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attr_map = dict(attrs)
        class_names = set((attr_map.get("class") or "").split())
        element_id = attr_map.get("id") or ""

        if tag in {"script", "style"}:
            self.skip_depth += 1
            return

        if tag == "div" and "body-content" in class_names and not self.in_body_content:
            self.in_body_content = True
            self.body_depth = 1
            return

        if self.in_body_content:
            self.body_depth += 1

        if self.in_body_content and self.target_section_id:
            if self.capture_depth > 0:
                self.capture_depth += 1
            elif element_id == self.target_section_id:
                self.capture_depth = 1

        if tag == "p" and self._is_capturing():
            self.in_paragraph = True
            self.current_paragraph = []

    def handle_endtag(self, tag: str) -> None:
        if self.skip_depth > 0 and tag in {"script", "style"}:
            self.skip_depth -= 1
            return

        if tag == "p" and self.in_paragraph:
            paragraph = " ".join("".join(self.current_paragraph).split())
            if paragraph:
                self.paragraphs.append(paragraph)
            self.in_paragraph = False
            self.current_paragraph = []

        if self.in_body_content:
            if self.target_section_id and self.capture_depth > 0:
                self.capture_depth -= 1

            self.body_depth -= 1
            if self.body_depth <= 0:
                self.in_body_content = False
                self.body_depth = 0
                self.capture_depth = 0

    def handle_data(self, data: str) -> None:
        if self.skip_depth > 0 or not self.in_paragraph or not self._is_capturing():
            return
        self.current_paragraph.append(data)

    def _is_capturing(self) -> bool:
        return self.in_body_content and (
            not self.target_section_id or self.capture_depth > 0
        )
        
if __name__ == "__main__":
    client = NCBIBooksClient()
    results = client.search_books("hernia")
    for res in results:
        print(f"Title: {res.title}")
        print(f"Source: {res.source}")
        print(f"Text source: {res.text_source}")
        print(f"URL: {res.url}")
        print(f"PDF URL found: {res.pdf_url_found}")
        print(f"PDF text extracted: {res.pdf_text_extracted}")
        if res.pdf_url:
            print(f"PDF: {res.pdf_url}")
        print(f"Text: {res.text[:200]}...")
        print(f"Text length: {len(res.text)} characters")
        print("-" * 60)