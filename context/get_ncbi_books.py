import time
from dotenv import load_dotenv
import os

from exa_py import Exa
from bs4 import BeautifulSoup
import requests
from markdownify import markdownify as md

from .config import RATE_LIMIT_DELAY 

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


class BookshelfClient:
    def __init__(self):
        self.exa = Exa(api_key=os.getenv("HCAI_API_KEY"), base_url="https://ai.hackclub.com/proxy/v1/exa")
        self.exa.headers["Authorization"] = f"Bearer {self.exa.headers['x-api-key']}"

    def get_ncbi_books(self, query: str, num_results: int = 5) -> str:
        response = self.exa.search(
            query, 
            num_results=num_results,
            type="instant",
            include_domains=["ncbi.nlm.nih.gov/books"],
            system_prompt="Extract relevant sections from NCBI Bookshelf entries related to the query.",
            contents=False
        )
        books = []
        for result in response.results:
            book = {
                "title": result.title,
                "url": result.url,
            }
            books.append(book)
        return books

    def get_book_html_content(self, url: str) -> str:
        time.sleep(RATE_LIMIT_DELAY)
        HEADERS.update({"User-Agent": USER_AGENTS[int(time.time()) % len(USER_AGENTS)]})
        response = requests.get(url, headers=HEADERS)
        print(response)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, "html.parser")
            content_div = soup.find("div", class_="document")
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

    def _html_to_md(self, html_content) -> str:
        if html_content:
            return md(str(html_content), heading_style="ATX", strip=["img", "a"])
        else:
            return "Failed to extract content."

    def get_book_contents(self, query: str, num_results: int = 5) -> list[dict]:
        books = self.get_ncbi_books(query, num_results)
        for book in books:
            html_content = self.get_book_html_content(book["url"])
            book["text"] = self._html_to_md(html_content)
        return books

if __name__ == "__main__":
    client = BookshelfClient()
    query = "inguinal hernia repair"
    books = client.get_book_contents(query, num_results=3)
    for book in books:
        print(f"Title: {book['title']}")
        print(f"URL: {book['url']}")
        print(f"Text:\n{book['text'][:300]}...")
        print("-" * 80)