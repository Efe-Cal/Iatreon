import asyncio
import os
import time
from typing import Optional
from urllib.parse import quote

import requests

from context.pmc import PMCClient

from .pdf_utils import PDFClient

from .models import Article

OPENALEX_BASE = "https://api.openalex.org"
OPENALEX_EMAIL = os.getenv("OPENALEX_EMAIL", "")
RATE_LIMIT_DELAY = 2

class OpenAlexClient:
    def __init__(self):
        self.pdf_client = PDFClient()
        self.pmc_client = PMCClient()
        
    def _headers(self):
        h = {}
        if OPENALEX_EMAIL:
            h["User-Agent"] = f"mailto:{OPENALEX_EMAIL}"
        return h

    def enrich_articles(self, articles: list[Article]) -> list[Article]:
        print(f"\n[OpenAlex] Enriching {len(articles)} articles with citations + PDF links...")
        enriched = 0

        for article in articles:
            if not article.doi:
                continue

            data = self._fetch_by_doi(article.doi)
            if not data:
                continue

            article.citation_count = data.get("cited_by_count", 0)
            article.openalex_id = data.get("id", "")
            article.keywords = [c["display_name"] for c in data.get("concepts", [])[:5]]

            if not article.study_type:
                article.study_type = data.get("type", "")

            if not article.full_text_available:
                oa = data.get("open_access", {})
                if oa.get("is_oa"):
                    pdf_url = oa.get("oa_url", "")
                    if pdf_url:
                        article.pdf_url = pdf_url
                        article.source = "OpenAlex OA PDF"
                        enriched += 1

            time.sleep(RATE_LIMIT_DELAY)

        print(f"[OpenAlex] Found PDF links for {enriched} additional articles")
        return articles
       

    def search_directly(self, query: str, max_results: int = 10) -> list[Article]:
        print(f"\n[OpenAlex] Direct search: '{query}'")

        params = {
            "search": query,
            "filter": "open_access.is_oa:true",
            "per-page": max_results,
            "select": "id,title,abstract_inverted_index,doi,cited_by_count,open_access,publication_year,authorships,primary_location,type,concepts",
        }

        r = requests.get(f"{OPENALEX_BASE}/works", params=params, headers=self._headers())
        r.raise_for_status()
        time.sleep(RATE_LIMIT_DELAY)
        print(f"[OpenAlex] Found {r.json().get('meta', {}).get('count', 0)} total results, returning top {max_results}")
        
        results = r.json().get("results", [])
        articles = []

        for item in results:
            a = Article()
            a.openalex_id = item.get("id", "")
            a.title = item.get("title", "")
            a.doi = item.get("doi", "").replace("https://doi.org/", "") if item.get("doi") else ""
            a.citation_count = item.get("cited_by_count", 0)
            a.year = item.get("publication_year", 0)
            a.study_type = item.get("type", "")

            inverted = item.get("abstract_inverted_index")
            if inverted:
                a.abstract = self._reconstruct_abstract(inverted)

            oa = item.get("open_access", {})
            if oa.get("is_oa") and oa.get("oa_url"):
                a.pdf_url = oa["oa_url"]
                a.source = "OpenAlex OA PDF"

            #TODO: Do the same for books (_extract_bookshelf_accession) when books work properly
            if not a.full_text_available:
                if pmc_id := PDFClient._extract_pmc_id(oa.get("oa_url", "")):
                    print(f"[OpenAlex] Found PMC ID {pmc_id}, getting full text...")
                    a.full_text = self.pmc_client.fetch_full_text(pmc_id)
                    a.full_text_available = bool(a.full_text)
                    a.source = "PMC XML Fetch"

            if a.pdf_url and not a.full_text_available:
                a.full_text = asyncio.run(self.pdf_client.get_pdf_content(a.pdf_url))
                a.full_text_available = bool(a.full_text)
                if not a.full_text_available:
                    a.source = "PDF Download Failed"
                    if a.abstract:
                        a.source += " (has abstract)"
                
            for auth in item.get("authorships", [])[:5]:
                name = auth.get("author", {}).get("display_name", "")
                if name:
                    a.authors.append(name)

            loc = item.get("primary_location", {}) or {}
            source = loc.get("source") or {}
            a.journal = source.get("display_name", "")

            a.keywords = [c["display_name"] for c in item.get("concepts", [])[:5]]
            articles.append(a)

        return articles

    def _fetch_by_doi(self, doi: str) -> Optional[dict]:
        encoded_doi = quote(doi, safe="")
        url = f"{OPENALEX_BASE}/works/https://doi.org/{encoded_doi}"
        try:
            r = requests.get(url, headers=self._headers())
            if r.status_code == 200:
                print(f"[OpenAlex] Found data for DOI: {doi}")
                return r.json()
        except Exception:
            pass
        return None

    def _reconstruct_abstract(self, inverted_index: dict) -> str:
        if not inverted_index:
            return ""
        word_positions = []
        for word, positions in inverted_index.items():
            for pos in positions:
                word_positions.append((pos, word))
        word_positions.sort(key=lambda x: x[0])
        return " ".join(word for _, word in word_positions)
    
if __name__ == "__main__":
    client = OpenAlexClient()
    data = client.search_directly("inguinal hernia", max_results=5)
    for article in data:
        print(f"\nTitle: {article.title}\nDOI: {article.doi}\nCitations: {article.citation_count}\nPDF: {article.pdf_url}\nFull Text Available: {article.full_text_available}\nSource: {article.source}\n\n---------------------\n\n")