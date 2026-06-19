from typing import AsyncGenerator
from dotenv import load_dotenv

from langchain_core.messages import AIMessageChunk
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import RunnableConfig

from agents.shared import create_agent_by_type, get_user_info, _iter_stream_text
from db.schemas import IntakeProfile
from db.db import checkpointer_manager

load_dotenv()

checkpointer = checkpointer_manager.get_checkpointer()


class DoctorAgent:
    def __init__(self):
        self.agent = create_agent_by_type("doctor", tools=[], checkpointer=checkpointer)

    async def run_doctor(self, message: str, conversation_id: str, user_id: str) -> AsyncGenerator[str | dict | tuple[IntakeProfile, list[dict[str, str]]], None]:
        config: RunnableConfig = {"configurable": {"thread_id": conversation_id}}
        messages = [
            {"role": "system", "content": await get_user_info(user_id=user_id)},
            {"role": "assistant", "content": "What brings you in today?"}
        ]

        self.agent.update_state(config=config, values={"messages": messages})
        
        async for event in self.agent.astream_events(
            {"messages": [{"role": "user", "content": message}]},
            config=config,
            version="v2",
        ):
            #TODO: Take a look a this when we have tools
            if event["event"] == "on_tool_start" or event["event"] == "on_tool_end":
                yield {"type": event["event"].removeprefix("on_"), "name": event["data"]["name"], "tool_call_id": event["run_id"]}
                
            if event["event"] == "on_chat_model_stream":
                chunk: AIMessageChunk = event["data"]["chunk"]
                for text in _iter_stream_text(chunk.content):
                    yield text
            