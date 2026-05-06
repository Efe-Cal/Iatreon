import json
import os

import requests

DEFAULT_EMAIL = os.getenv("UNPAYWALL_EMAIL") or os.getenv("OPENALEX_EMAIL") or "you@email.com"
UNPAYWALL_BASE = "https://api.unpaywall.org/v2"
REQUEST_TIMEOUT = 20


def get_free_pdf_url(doi: str, email: str = "") -> str:
    contact_email = email or DEFAULT_EMAIL
    if not doi or not contact_email:
        return ""

    try:
        response = requests.get(
            f"{UNPAYWALL_BASE}/{doi}",
            params={"email": contact_email},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        print(f"[Unpaywall] Data for DOI {doi}: {json.dumps(data, indent=2)}")
    except (requests.RequestException, ValueError) as exc:
        print(f"[Unpaywall] Failed to fetch PDF URL for DOI {doi}: {exc}")
        return ""

    if not data.get("is_oa"):
        return ""

    best_location = data.get("best_oa_location") or {}
    return best_location.get("url_for_pdf") or ""


def enrich_with_pdf(articles):
    for article in articles:
        if article.doi and not article.full_text_available and not article.pdf_url:
            article.pdf_url = get_free_pdf_url(article.doi)
    return articles


if __name__ == "__main__":
    doi = "10.1056/nejmoa040093"
    pdf_url = get_free_pdf_url(doi)
    print(f"PDF URL for DOI {doi}: {pdf_url}")
