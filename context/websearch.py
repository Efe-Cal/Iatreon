import os

from exa_py import Exa
from exa_py.api import ContentsOptions
from dotenv import load_dotenv

load_dotenv()

exa = Exa(api_key=os.getenv("HCAI_API_KEY"), base_url="https://ai.hackclub.com/proxy/v1/exa")
exa.headers["Authorization"] = f"Bearer {exa.headers['x-api-key']}"

def web_search(query: str, num_results: int = 5):
    response = exa.search(query, num_results=num_results, 
                          contents=ContentsOptions(livecrawl="preferred"))
    return response
