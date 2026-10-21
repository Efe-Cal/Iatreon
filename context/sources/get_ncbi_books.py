from dotenv import load_dotenv
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from markdownify import markdownify as md

from context.models import BookSection

from ..errors import log_external_failure
from ..websearch import make_exa_client
from .ncbi_rate_limit import ncbi_get

load_dotenv()


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

_NCBI_BOOKS_HOSTS = {"ncbi.nlm.nih.gov", "www.ncbi.nlm.nih.gov"}
_ACCESSION_RE = re.compile(r"^[A-Za-z0-9_]+$")
_MAX_REDIRECTS = 5


def normalize_bookshelf_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in _NCBI_BOOKS_HOSTS:
        raise ValueError("Bookshelf URL must use HTTPS on ncbi.nlm.nih.gov")
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("Bookshelf URL contains an invalid authority")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or parts[0] != "books" or not _ACCESSION_RE.fullmatch(parts[1]):
        raise ValueError("Bookshelf URL must contain a safe /books/<accession>/ path")
    return f"https://www.ncbi.nlm.nih.gov/books/{parts[1]}/"


class BookshelfClient:
    def __init__(self):
        self.exa = make_exa_client()

    def get_ncbi_books(self, query: str, num_results: int = 5) -> list[dict]:
        try:
            response = self.exa.search(
                query,
                num_results=num_results,
                type="instant",
                include_domains=["ncbi.nlm.nih.gov/books"],
                system_prompt="Extract relevant sections from NCBI Bookshelf entries related to the query.",
                contents=False
            )
        except Exception as exc:
            log_external_failure("Exa", "Bookshelf search", exc)
            return []

        books = []
        for result in response.results:
            try:
                url = normalize_bookshelf_url(result.url)
            except (TypeError, ValueError) as exc:
                log_external_failure("NCBI Bookshelf", "result URL validation", exc)
                continue
            book = {
                "title": result.title,
                "url": url,
                "accession_id": url.split("/")[-2],
                "source": "NCBI Bookshelf",
            }
            books.append(book)
        return books

    def _get_bookshelf_response(self, url: str, headers: dict):
        current_url = normalize_bookshelf_url(url)
        for _ in range(_MAX_REDIRECTS + 1):
            response = ncbi_get(current_url, headers=headers, allow_redirects=False)
            if not response.is_redirect:
                return response
            location = response.headers.get("Location")
            if not location:
                raise ValueError("Bookshelf redirect did not include a Location header")
            current_url = normalize_bookshelf_url(urljoin(current_url, location))
        raise ValueError("Bookshelf exceeded the redirect limit")

    def get_book_html_content(self, url: str) -> str:
        try:
            url = normalize_bookshelf_url(url)
        except (TypeError, ValueError) as exc:
            log_external_failure("NCBI Bookshelf", "HTML URL validation", exc)
            return ""
        headers = HEADERS.copy()
        headers.update({"User-Agent": USER_AGENTS[hash(url) % len(USER_AGENTS)]})
        try:
            response = self._get_bookshelf_response(url, headers)
        except Exception as exc:
            log_external_failure("NCBI Bookshelf", "HTML fetch", exc)
            return ""

        if response.status_code == 200:
            soup = BeautifulSoup(response.content, "html.parser")
            content_div = soup.find("div", class_="document")
            if content_div is None:
                log_external_failure("NCBI Bookshelf", "HTML parse", "missing document content")
                return ""
            # Remove some divs that are not relevant
            for div in content_div.find_all("div", class_=["pre-content","post-content"]):
                div.decompose()
                
            # Remove attributeless divs
            for div in content_div.find_all(lambda tag: tag.name == "div" and not tag.attrs):
                div.decompose()
        
            # Remove references section
            for header in content_div.find_all(['h2', 'h3', 'div']):
                if header.get_text(strip=True).lower() == "references":
                    parent = header.find_parent("div")
                    if parent:
                        parent.decompose()
                    else:
                        header.decompose()

            # Remove affiliations and author info
            for span in content_div.find_all("span"):
                if "affiliation" in span.get_text(strip=True).lower() or "author" in span.get_text(strip=True).lower():
                    parent = span.find_parent("a")
                    if parent:
                        parent.decompose()
                    else:
                        span.decompose()
            
            return content_div
        log_external_failure("NCBI Bookshelf", "HTML fetch", f"status {response.status_code}")
        return ""

    def _html_to_md(self, html_content) -> str:
        if html_content:
            return md(str(html_content), heading_style="ATX", strip=["img", "a"])
        else:
            return "Failed to extract content."

    def get_book_contents(self, query: str, num_results: int = 5) -> list[BookSection]:
        books = self.get_ncbi_books(query, num_results)
        for book in books:
            try:
                html_content = self.get_book_html_content(book["url"])
            except Exception as exc:
                log_external_failure("NCBI Bookshelf", "book content fetch", exc)
                html_content = "Failed to extract content."
            book["text"] = self._html_to_md(html_content)
            if book["text"] and book["text"] != "Failed to extract content.":
                book["full_text_available"] = True
        
        return [BookSection(**book) for book in books]

if __name__ == "__main__":
    client = BookshelfClient()
    query = "inguinal hernia repair"
    books = client.get_book_contents(query, num_results=3)
    for book in books:
        print(f"Title: {book.title}")
        print(f"URL: {book.url}")
        print(f"Text:\n{book.text[:300]}...")
        print("-" * 80)
