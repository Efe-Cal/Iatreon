import os

from exa_py import Exa
from exa_py.api import ContentsOptions, TextContentsOptions, HighlightsContentsOptions
from dotenv import load_dotenv

from langchain.tools import tool

load_dotenv()

exa = Exa(api_key=os.getenv("HCAI_API_KEY"), base_url="https://ai.hackclub.com/proxy/v1/exa")
exa.headers["Authorization"] = f"Bearer {exa.headers['x-api-key']}"


def web_search(query: str, num_results: int = 5):
    """Performs a web search using the Exa API and returns the highlights for each result.
    
    Args:
        query (str): The search query.
        num_results (int): The number of results to return.

    Returns:
        The search highlights.
    """
    response = exa.search(
        query, 
        num_results=num_results,
        type="deep",
        system_prompt="Prefer recent information from articles and medical sources.",
        contents=ContentsOptions(livecrawl="preferred",
                    text=TextContentsOptions(),
                    highlights=HighlightsContentsOptions(
                        query="""BE EXTREAMLY detailed and comprehensive. Extract ALL clinically relevant information.

Prioritize:
- symptoms
- differential diagnoses
- prevalence
- risk factors
- contraindications
- treatment options
- treatment failures
- adverse effects
- rare complications
- diagnostic criteria
- imaging findings
- prognosis
- edge cases
- conflicting evidence
- special populations
- pediatric considerations
- geriatric considerations
- pregnancy considerations
- drug interactions
- dosage details
- monitoring recommendations

Avoid omitting nuanced or uncertain findings.
Prefer completeness over brevity."""
            )))

    return [{"title": r.title, "url": r.url, "highlights": r.highlights} for r in response.results]

def fetch_web_content(url: str) -> str:
    """Fetches the full contents of a web page.
    
    Args:
        url (str): The URL of the web page to fetch.

    Returns:
        The text content of the web page.
    """
    
    response = exa.get_contents(url, livecrawl="preferred", text=TextContentsOptions())
    if response.statuses[0].status != "success":
        return "Failed to fetch content."
    return response.results[0].text

if __name__ == "__main__":
    # results = web_search("inguinal hernia repair", num_results=3)
    # for r in results:
    #     print(f"Title: {r.get('title')}")
    #     print(f"URL: {r.get('url')}")
    #     print(f"Highlights: {r.get('highlights')}")
    #     print("-" * 80)
    content = fetch_web_content("https://emedicine.medscape.com/article/189563-overview")
    print(content)