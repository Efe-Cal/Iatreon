import time
import xml.etree.ElementTree as ET

import requests

from .config import NCBI_API_KEY, NCBI_BASE, RATE_LIMIT_DELAY
from .models import Article


class PubMedClient:
    def search(self, query: str, max_results: int = 20) -> list[str]:
        """Search PubMed and return a list of PubMed IDs."""
        print(f"\n[PubMed] Searching: '{query}' (max {max_results} results)")

        params = {
            "db": "pubmed",
            "term": query,
            "retmax": max_results,
            "retmode": "json",
            "sort": "relevance",
        }
        if NCBI_API_KEY:
            params["api_key"] = NCBI_API_KEY

        r = requests.get(f"{NCBI_BASE}/esearch.fcgi", params=params)
        r.raise_for_status()
        try:
            ids = r.json()["esearchresult"]["idlist"]
        except requests.exceptions.JSONDecodeError:
            print(f"Error decoding JSON for query: {query}")
            print(f"Response content: {r.text}")
            return []
        print(f"[PubMed] Found {len(ids)} articles")
        return ids

    def fetch_abstracts(self, pubmed_ids: list[str]) -> list[Article]:
        """Fetch titles, abstracts, and metadata for a list of PubMed IDs."""
        if not pubmed_ids:
            return []

        print(f"[PubMed] Fetching metadata for {len(pubmed_ids)} articles...")

        params = {
            "db": "pubmed",
            "id": ",".join(pubmed_ids),
            "rettype": "xml",
            "retmode": "xml",
        }
        if NCBI_API_KEY:
            params["api_key"] = NCBI_API_KEY

        r = requests.get(f"{NCBI_BASE}/efetch.fcgi", params=params)
        r.raise_for_status()
        time.sleep(RATE_LIMIT_DELAY)

        return self._parse_pubmed_xml(r.text)

    def _parse_pubmed_xml(self, xml_text: str) -> list[Article]:
        articles = []
        root = ET.fromstring(xml_text)

        for article_elem in root.findall(".//PubmedArticle"):
            a = Article()

            pmid_elem = article_elem.find(".//PMID")
            if pmid_elem is not None:
                a.pubmed_id = pmid_elem.text

            title_elem = article_elem.find(".//ArticleTitle")
            if title_elem is not None:
                a.title = "".join(title_elem.itertext()).strip()

            abstract_texts = article_elem.findall(".//AbstractText")
            abstract_parts = []
            for ab in abstract_texts:
                label = ab.get("Label", "")
                text = "".join(ab.itertext()).strip()
                abstract_parts.append(f"{label}: {text}" if label else text)
            a.abstract = "\n".join(abstract_parts)

            for id_elem in article_elem.findall(".//ArticleId"):
                if id_elem.get("IdType") == "doi":
                    a.doi = id_elem.text or ""
                if id_elem.get("IdType") == "pmc":
                    a.pmc_id = id_elem.text or ""

            journal_elem = article_elem.find(".//Journal/Title")
            if journal_elem is not None:
                a.journal = journal_elem.text or ""

            year_elem = article_elem.find(".//PubDate/Year")
            if year_elem is not None:
                try:
                    a.year = int(year_elem.text)
                except (ValueError, TypeError):
                    pass

            for author in article_elem.findall(".//Author"):
                last = author.find("LastName")
                first = author.find("ForeName")
                if last is not None:
                    name = last.text or ""
                    if first is not None:
                        name += f", {first.text}"
                    a.authors.append(name)

            for mesh in article_elem.findall(".//MeshHeading/DescriptorName"):
                if mesh.text:
                    a.mesh_terms.append(mesh.text)

            pub_types = article_elem.findall(".//PublicationType")
            for pt in pub_types:
                if pt.text:
                    a.study_type = pt.text
                    break

            articles.append(a)

        return articles

if __name__ == "__main__":
    client = PubMedClient()
    ids = client.search("inguinal hernia", max_results=5)
    articles = client.fetch_abstracts(ids)
    for article in articles:
        print(f"\nTitle: {article.title}\nDOI: {article.doi}\nPMCID: {article.pmc_id}\nJournal: {article.journal}\nYear: {article.year}\nAuthors: {', '.join(article.authors)}\nMesh Terms: {', '.join(article.mesh_terms)}\nStudy Type: {article.study_type}\nAbstract: {article.abstract[:200]}...")