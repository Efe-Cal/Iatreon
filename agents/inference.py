import logging
from dotenv import load_dotenv

from agents.shared import create_agent_by_type, web_search_tool

load_dotenv()

inference_agent = create_agent_by_type("inference", tools=[web_search_tool])

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
