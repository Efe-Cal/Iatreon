import os
from typing import AsyncGenerator
from dotenv import load_dotenv

from langchain_core.messages import AIMessageChunk
from langchain.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import RunnableConfig

from agents.shared import create_agent_by_type, get_model, get_user_info, _iter_stream_text
from agents.inference import run_inference

from db.schemas import IntakeProfile
from db.db import checkpointer_manager

from .mock_patient import mock_patient_response

load_dotenv()


@tool("end_of_intake", return_direct=True)
def end_of_intake():
    """Tool to signal the end of the intake process."""
    return "Intake process has been completed."

@tool("infer_condition")
async def infer_condition(summary: str) -> str:
    """Tool to infer potential conditions based on patient's chief complaint and HPI.
    The input should be a markdown-formatted summary of the patient's chief complaint and HPI details."""
    
    return await run_inference(summary)

agent = None


def get_intake_agent():
    global agent
    if agent is None:
        agent = create_agent_by_type(
            "intake",
            tools=[end_of_intake, infer_condition],
            checkpointer=checkpointer_manager.get_checkpointer(),
        )
    return agent

async def run_intake_cli(message: str, conversation_id: str, user_id: str) -> AsyncGenerator[str | dict | tuple[IntakeProfile, list[dict[str, str]]], None]:
    agent = get_intake_agent()
    config: RunnableConfig = {"configurable": {"thread_id": conversation_id}}
    state = await agent.aget_state(config=config)
    if not state.values.get("messages"):
        messages = [
            {"role": "system", "content": await get_user_info(user_id=user_id)}
        ]
        await agent.aupdate_state(config=config, values={"messages": messages})
    
    end_intake_called = False
    infer_condition_active = False
    if message.strip() == ".":
        state = await agent.aget_state(config=config)
        message = await mock_patient_response(state.values["messages"].copy())
        yield f"**Patient:** {message}   \n\n\n\n\n"

    async for event in agent.astream_events(
        {"messages": [{"role": "user", "content": message}]},
        config=config,
        version="v2",
    ):
        if event["event"] == "on_tool_start":
            if event.get("name") == "end_of_intake":
                end_intake_called = True

            elif event.get("name") == "infer_condition":
                infer_condition_active = True
                # tool_input = event["data"]["input"]["summary"]
                yield {"type": "tool_start", "name": "infer_condition", "tool_call_id": event["run_id"]}
            continue

        elif event["event"] == "on_tool_end":
            if event.get("name") == "infer_condition":
                infer_condition_active = False
                yield {"type": "tool_end", "name": "infer_condition", "tool_call_id": event["run_id"]}
            continue

        if event["event"] == "on_chat_model_stream":
            if infer_condition_active:
                continue

            chunk: AIMessageChunk = event["data"]["chunk"]
            for text in _iter_stream_text(chunk.content):
                yield text

    if end_intake_called:
        model = get_model("intake", 0.3)  # Get the model instance
        structured_model = model.with_structured_output(IntakeProfile)

        try:
            conversation_state = await agent.aget_state(config=config)
            final_patient_data = await structured_model.ainvoke(conversation_state.values["messages"])

            yield f"I have compiled the final patient data."
            yield final_patient_data, conversation_state.config["configurable"]["thread_id"]
        except Exception as e:
            print(f"\nFailed to generate final report: {e}")

if __name__ == "__main__":
    async def main():
        async for chunk in run_intake_cli("I have abdominal pain"):
            print(chunk)
            
    import asyncio
    asyncio.run(main())
