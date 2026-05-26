import logging
import os
from dotenv import load_dotenv

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from context.websearch import web_search
from langchain.tools import tool

load_dotenv()

model = ChatOpenAI(model=os.getenv("INFERENCE_AGENT_MODEL") or os.getenv("INTAKE_AGENT_MODEL") or "google/gemini-3-flash-preview",
                   base_url=os.getenv("AI_API_BASE_URL") or "https://ai.hackclub.com/proxy/v1",
                   api_key=os.getenv("AI_API_KEY"),
                   temperature=0.7)

with open(os.path.join(__file__, "..", "prompts", "inference_agent_system_prompt.txt")) as f:
    system_prompt = f.read()

inference_agent = create_agent(
    model=model,
    tools=[tool(web_search)],
    system_prompt=system_prompt,
)


def _content_to_text(content: str | list[dict] | None) -> str:
    if isinstance(content, str):
        return content

    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
            parts.append(block["text"])

    return "".join(parts)


async def run_inference(summary: str) -> str:
    user_message = "Patient Summary:\n\n" + summary + \
    "\n\nBased on the patient's chief complaint and HPI details provided above, please generate a ranked differential diagnosis and identify critical information gaps. Use the `web_search` tool if you need to look up any medical information to inform your reasoning. Return your response in a structured format with sections for Differential (ranked), Critical Unknowns, and Recommended Focus Areas."
    
    messages = [{"role": "user", "content": user_message}]
    response = await inference_agent.ainvoke({"messages": messages})
    logging.debug(f"Inference agent response: {response}")
    return _content_to_text(response["messages"][-1].content)
