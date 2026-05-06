import os

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langchain.tools import tool

from context.pipeline import MedicalKnowledgePipeline
from context.websearch import web_search
from context.openalex import OpenAlexClient

DATABASE = {}

 
openalex = OpenAlexClient()

model = ChatOpenAI(model="gemini-3-flash-preview",
                   base_url="https://ai.hackclub.com/proxy/v1",
                   api_key=os.getenv("HCAI_API_KEY"),
                   temperature=0.5)

with open("context/context_agent_system_prompt.txt") as f:
    system_prompt = f.read()

@tool
def search_openalex(query: str) -> str:
    """Searches OpenAlex for articles related to the query.
    
    Args:
        query (str): The search query.

    Returns:
        A list of relevant articles.
    """
    results = openalex.search_directly(query, max_results=3)
    if not results:
        return "No relevant articles found in OpenAlex."
    
    response = "Top OpenAlex results:\n"
    for article in results:
        response += f"- {article.title}\n"
        if article.pdf_url:
            response += f"  PDF: {article.pdf_url}\n"
    return response

@tool
def search_pubmed(query: str) -> str:
    """Searches PubMed for articles related to the query.
    
    Args:
        query (str): The search query.
    
    Returns:
        A list of relevant articles.
    """
    pipeline = MedicalKnowledgePipeline()
    pipeline_results = pipeline.get_json_content(query, max_articles=5, include_books=False)
    DATABASE["pubmed_"+query] = pipeline_results
    return "Articles retrieved:\n" + "\n".join([f"- {a['title']}" for a in pipeline_results["articles"]])

agent = create_agent(model=model,
                     tools=[web_search, search_openalex, search_pubmed], 
                     verbose=True,
                     system_prompt=system_prompt)