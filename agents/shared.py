import os
from typing import Literal, Any
from dotenv import load_dotenv
import asyncio

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langgraph.graph.state import CompiledStateGraph
from langchain_core.tools import tool

from context.websearch import web_search
from db.db import read_only_session
from db.repositories import UserRepo

load_dotenv()

Agent = Literal["intake", "research", "diagnosis", "inference"]

def get_model(agent_type: Agent, temperature: float = 0.7) -> ChatOpenAI:
    model_name = os.getenv(f"{agent_type.upper()}_AGENT_MODEL")
    return ChatOpenAI(model=model_name or "google/gemini-3-flash-preview",
                      base_url=os.getenv("AI_API_BASE_URL") or "https://ai.hackclub.com/proxy/v1",
                      api_key=os.getenv("AI_API_KEY"),
                      temperature=temperature)

def load_system_prompt(agent_type: Agent) -> str:
    with open(os.path.join(__file__, "..", "prompts", f"{agent_type}_agent_system_prompt.txt")) as f:
        return f.read()

def create_agent_by_type(
    agent_type: Agent,
    tools: list,
    temperature: float = 0.7,
    system_prompt_format: dict | None = None,
    **kwargs
) -> CompiledStateGraph[Any, Any, Any, Any]:
    model = get_model(agent_type, temperature)
    system_prompt = load_system_prompt(agent_type).format(**(system_prompt_format or {}))
    
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        **kwargs
    )

@tool("web_search")
async def web_search_tool(query: str, num_results: int = 5):
    """Performs a web search using the Exa API and returns the highlights for each result.
    
    Args:
        query (str): The search query.
        num_results (int): The number of results to return.

    Returns:
        The search highlights.
    """
    return await asyncio.to_thread(web_search, query, num_results)


async def get_user_info(user_id: str):
    user_repo = UserRepo()
    async with read_only_session() as db:
        info = "# Patient Profile\n"
        user_profile = await user_repo.get_user_profile(db, user_id)
        
        info += f"## Demographics:\n"
        demographics = user_profile["demographics"]
        for key, value in demographics.items():
            info += f"{key.capitalize()}: {value}\n"
        
        allergies = user_profile["allergies"]
        if allergies:
            info += "## Allergies:\n"
            for allergy in allergies:
                info += f"- {allergy}\n"
        
        medications = user_profile["medications"]
        if medications:
            info += "## Medications:\n"
            for medication in medications:
                info += f"- {medication}\n"
        
        social = user_profile["social"]
        if social:
            info += "## Social History:\n"
            for key, value in social.items():
                info += f"{key.capitalize()}: {value}\n"
        
        return info