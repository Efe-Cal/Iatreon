import os

from exa_py import Exa
from exa_py.api import ContentsOptions, TextContentsOptions, HighlightsContentsOptions
from dotenv import load_dotenv

from context.errors import log_external_failure
from local_worker.provider_config import provider_setup, search_config

load_dotenv()

exa = Exa(api_key=os.getenv("EXA_API_KEY", os.getenv("AI_API_KEY")), base_url=os.getenv("EXA_BASE_URL", "https://ai.hackclub.com/proxy/v1/exa"))
exa.headers["Authorization"] = f"Bearer {exa.headers['x-api-key']}"


def make_exa_client():
    if not provider_setup():
        return exa

    config = search_config()

    kwargs = {"api_key": config["api_key"]}
    if config["base_url"]:
        kwargs["base_url"] = config["base_url"]

    client = Exa(**kwargs)
    if client.headers.get("x-api-key"):
        client.headers["Authorization"] = f"Bearer {client.headers['x-api-key']}"
    return client


def web_search(query: str, num_results: int = 5):
    """Performs a web search using the Exa API and returns the highlights for each result.
    
    Args:
        query (str): The search query.
        num_results (int): The number of results to return.

    Returns:
        The search highlights.
    """
    try:
        response = make_exa_client().search(
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
    except Exception as exc:
        log_external_failure("Exa", "search", exc)
        return []

    return [{"title": r.title, "url": r.url, "highlights": r.highlights} for r in response.results]

def fetch_web_content(url: str) -> str:
    """Fetches the full contents of a web page.
    
    Args:
        url (str): The URL of the web page to fetch.

    Returns:
        The text content of the web page.
    """
    
    try:
        response = make_exa_client().get_contents(url, livecrawl="preferred", text=TextContentsOptions())
    except Exception as exc:
        log_external_failure("Exa", "content fetch", exc)
        return "Failed to fetch content."

    if not response.statuses or response.statuses[0].status != "success" or not response.results:
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
