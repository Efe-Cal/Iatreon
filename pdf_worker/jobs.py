import os

from pdf_worker.scraper import Scraper

scraper: Scraper | None = None


def get_scraper() -> Scraper:
    global scraper
    if scraper is None:
        scraper = Scraper()
    return scraper

def fetch_pdf(pdf_urls: str):
    file_path = get_scraper().download_pdf(pdf_urls)
    return file_path
