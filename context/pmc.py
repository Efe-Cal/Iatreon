import os
import time
import xml.etree.ElementTree as ET
from typing import Optional

import requests

from .models import Article

NCBI_API_KEY = os.getenv("NCBI_API_KEY", "")
NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

RATE_LIMIT_DELAY = 2


class PMCClient:
    def get_pmc_id(self, pubmed_id: str) -> Optional[str]:
        """Check if a PubMed article has a free PMC full-text version."""
        params = {
            "dbfrom": "pubmed",
            "db": "pmc",
            "id": pubmed_id,
            "retmode": "json",
        }
        if NCBI_API_KEY:
            params["api_key"] = NCBI_API_KEY

        try:
            r = requests.get(f"{NCBI_BASE}/elink.fcgi", params=params)
            r.raise_for_status()
        except Exception as e:
            print(f"Error fetching PMC ID for PubMed ID {pubmed_id}: {e}")
            time.sleep(RATE_LIMIT_DELAY)
            return None

        time.sleep(RATE_LIMIT_DELAY)

        try:
            links = r.json()["linksets"][0]["linksetdbs"][0]["links"]
            return str(links[0]) if links else None
        except (KeyError, IndexError):
            return None
        except requests.exceptions.JSONDecodeError:
            print(f"Error decoding JSON for PubMed ID: {pubmed_id}")
            return None

    def fetch_full_text(self, pmc_id: str) -> str:
        """Fetch and parse full article text from PMC."""
        params = {
            "db": "pmc",
            "id": pmc_id,
            "rettype": "xml",
            "retmode": "xml",
        }
        if NCBI_API_KEY:
            params["api_key"] = NCBI_API_KEY

        r = requests.get(f"{NCBI_BASE}/efetch.fcgi", params=params)
        r.raise_for_status()
        time.sleep(RATE_LIMIT_DELAY)

        return self._extract_text_from_xml(r.text)

    def _extract_text_from_xml(self, xml_text: str) -> str:
        """Extract readable text from PMC XML, preserving structure."""
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return ""

        sections = []

        for sec in root.findall(".//sec"):
            title_elem = sec.find("title")
            section_title = title_elem.text if title_elem is not None else "Section"

            paragraphs = []
            for p in sec.findall(".//p"):
                text = "".join(p.itertext()).strip()
                if text:
                    paragraphs.append(text)

            if paragraphs:
                sections.append(f"\n## {section_title}\n" + "\n".join(paragraphs))

        if not sections:
            for p in root.findall(".//p"):
                text = "".join(p.itertext()).strip()
                if text:
                    sections.append(text)

        return "\n".join(sections)

    def enrich_articles_with_fulltext(self, articles: list[Article]) -> list[Article]:
        """Try to get PMC full text for each article."""
        print(f"\n[PMC] Attempting full text retrieval for {len(articles)} articles...")
        success = 0

        for article in articles:
            pmc_id = article.pmc_id

            if not pmc_id and article.pubmed_id:
                pmc_id = self.get_pmc_id(article.pubmed_id)

            if pmc_id:
                full_text = self.fetch_full_text(pmc_id)
                if full_text:
                    article.pmc_id = pmc_id
                    article.full_text = full_text
                    article.full_text_available = True
                    article.source = "PMC Full Text"
                    success += 1

        print(f"[PMC] Retrieved full text for {success}/{len(articles)} articles")
        return articles