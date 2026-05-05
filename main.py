import os

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from context.websearch import web_search
from context.openalex import OpenAlexClient
 
openalex = OpenAlexClient()

model = ChatOpenAI(model="gpt-4o",
                   base_url="https://ai.hackclub.com/proxy/v1",
                   api_key=os.getenv("HCAI_API_KEY"),
                   temperature=0.5)

agent = create_agent(model=model, tools=[web_search, openalex.search_directly], verbose=True)