import logging
import os
from dotenv import load_dotenv

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from context.websearch import web_search
from langchain.tools import tool

from db.models import IntakeSession, ResearchSession

load_dotenv()

model = ChatOpenAI(model=os.getenv("INFERENCE_AGENT_MODEL") or os.getenv("INTAKE_AGENT_MODEL") or "google/gemini-3-flash-preview",
                   base_url=os.getenv("AI_API_BASE_URL") or "https://ai.hackclub.com/proxy/v1",
                   api_key=os.getenv("AI_API_KEY"),
                   temperature=0.7)

with open(os.path.join(__file__, "..", "prompts", "diagnosis_system_prompt.txt")) as f:
    system_prompt = f.read()

#TODO: proper system prompt; get_full_source tool
diagnosis_agent = create_agent(
    model=model,
    tools=[tool(web_search)],
    system_prompt=system_prompt,
)

async def diagnose(intake_session: IntakeSession, research_session: ResearchSession):
    logging.info("Starting diagnosis agent")
    user_message = f"""# Patient Information
Chief complaint: {intake_session.chief_complaint or "N/A"}
Medical Summary: {intake_session.medical_summary}"""
    if research_session and research_session.research_report:
        user_message += f"\n\n# Research Findings\n{research_session.research_report}"
    
    logging.debug(f"Diagnosis agent input message: {user_message}")
    
    response = await diagnosis_agent.ainvoke(user_message)
    return response["messages"][-1].content