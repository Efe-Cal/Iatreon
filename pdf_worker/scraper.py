import os
from urllib.parse import urlparse, urljoin
import uuid
from seleniumbase import sb_cdp
import httpx

PROFILE_DIR = os.path.join(__file__, "..", "chrome_profile")
os.makedirs(PROFILE_DIR, exist_ok=True)

def _is_probable_pdf_url(url: str) -> bool:
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

class Scraper:
    def __init__(self):
        print(f"Loading persistent session from: {PROFILE_DIR}")
        self.sb = sb_cdp.Chrome(uc=True, user_data_dir=PROFILE_DIR)
    
    def run_scraper(self):

        self.sb.open("https://www.ncbi.nlm.nih.gov/pmc/articles/8307506/")
        
        self.sb.sleep(3)
        
        self.sb.solve_captcha()
        self.sb.sleep(2)
        
        pdf = self.sb.find_element_by_text("PDF")
        for attr in ["href", "aria-label", "title", "content"]:
            try:
                value = pdf.get_attribute(attr)
                print(f"Checking attribute '{attr}': {value}")
                if value and _is_probable_pdf_url(value):
                    print(f"Found PDF URL: {value}")
                    pdf_content = self.request_pdf_with_session(value)
                    with open("downloaded.pdf", "wb") as f:
                        f.write(pdf_content)
                    break
            except Exception as e:
                import traceback
                print(f"Error while processing attribute '{attr}': {e}")
                traceback.print_exc()
                continue
        
        self.sb.sleep(5)
        
        self.sb.quit()

    def request_pdf_with_session(self, url):
        # 1. Ensure absolute URL
        absolute_url = urljoin(self.sb.get_current_url(), url)
        
        # 2. Extract current User-Agent to match the browser exactly
        user_agent = self.sb.evaluate("navigator.userAgent")
        
        headers = {
            "User-Agent": user_agent,
            "Referer": self.sb.get_current_url(),
            "Accept": "application/pdf,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }

        cookies = self.sb.get_all_cookies()
        
        # sb_cdp returns Cookie objects, so we access attributes using .name instead of ['name']
        httpx_cookies = {cookie.name: cookie.value for cookie in cookies}

        print(f"Absolute URL to download: {absolute_url}")
        response = httpx.get(
            absolute_url, 
            cookies=httpx_cookies, 
            headers=headers, 
            follow_redirects=True
        )        
        response.raise_for_status()

        return response.content

if __name__ == "__main__":
    scraper = Scraper()
    scraper.run_scraper()