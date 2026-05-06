import os

from exa_py import Exa
from exa_py.api import ContentsOptions, TextContentsOptions, HighlightsContentsOptions
from dotenv import load_dotenv

from langchain.tools import tool

load_dotenv()

exa = Exa(api_key=os.getenv("HCAI_API_KEY"), base_url="https://ai.hackclub.com/proxy/v1/exa")
exa.headers["Authorization"] = f"Bearer {exa.headers['x-api-key']}"


# @tool
def web_search(query: str, num_results: int = 5):
    """Performs a web search using the Exa API and returns the results.
    
    Args:
        query (str): The search query.
        num_results (int): The number of results to return.

    Returns:
        The search results.
    """
    response = exa.search(query, num_results=num_results,
                          system_prompt="Prefer recent information from articles and medical sources.",
                          contents=ContentsOptions(livecrawl="preferred",
                                                   text=TextContentsOptions(),
                                                   highlights=HighlightsContentsOptions(
                                                       query="BE EXTREAMLY detailed and comprehensive."
                                                   )))
    return response

# @tool
def fetch_web_content(url: str) -> str:
    """Fetches the content of a web page using the Exa API.
    
    Args:
        url (str): The URL of the web page to fetch.

    Returns:
        The content of the web page.
    """
    response = exa.get_contents(url).results[0].text
    return response

if __name__ == "__main__":
    results = web_search("inguinal hernia repair", num_results=3)
    for r in results.results:
        print(f"Title: {r.title}")
        print(f"URL: {r.url}")
        print(f"Highlights: {r.highlights}")
        print("-" * 80)
    # content = fetch_web_content("https://www.uptodate.com/contents/open-surgical-repair-of-inguinal-and-femoral-hernia-in-adults")
    # print(content)