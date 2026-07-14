from pdf_worker.scraper import Scraper
from pdf_worker.security import validate_public_http_url

scraper: Scraper | None = None


def get_scraper() -> Scraper:
    global scraper
    if scraper is None:
        scraper = Scraper()
    return scraper

def fetch_pdf(pdf_urls: str):
    validate_public_http_url(pdf_urls)
    file_path = get_scraper().download_pdf(pdf_urls)
    return file_path
