from typing import AsyncGenerator
import uuid
import logging
from dotenv import load_dotenv

from langchain_core.messages import AIMessageChunk
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import RunnableConfig
import os

from agents.research import EFFORT_SETTINGS, ResearchAgent, ResearchEffort
from agents.shared import create_agent_by_type, get_user_info, _iter_stream_text
from db.schemas import IntakeProfile

load_dotenv()

class DoctorAgent:
    def __init__(self, user_id: str | None = None, chat_session_id: uuid.UUID | None = None):
        self.user_id: str | None = user_id
        self.chat_session_id: uuid.UUID | None = chat_session_id
        self.call_research_agent_tool = StructuredTool.from_function(
            coroutine=self._call_research_agent,
            name="call_research_agent",
            description=(
                "Request focused medical research for a patient question. "
                "Choose research_effort as fast, standard, deep, or web."
            ),
        )
        if os.getenv("IATREON_LOCAL_WORKER") == "1":
            checkpointer = InMemorySaver()
        else:
            from db.db import checkpointer_manager
            checkpointer = checkpointer_manager.get_checkpointer()
        self.agent = create_agent_by_type(
            "doctor",
            tools=[self.call_research_agent_tool],
            checkpointer=checkpointer,
        )

    async def run_doctor(self, message: str, conversation_id: str) -> AsyncGenerator[str | dict | tuple[IntakeProfile, list[dict[str, str]]], None]:
        config: RunnableConfig = {"configurable": {"thread_id": conversation_id}}
        state = await self.agent.aget_state(config=config)
        if not state.values.get("messages"):
            messages = [
                {"role": "system", "content": await get_user_info(user_id=self.user_id)}
            ]
            await self.agent.aupdate_state(config=config, values={"messages": messages})
        
        try:
            async for event in self.agent.astream_events(
                {"messages": [{"role": "user", "content": message}]},
                config=config,
                version="v2",
            ):
                #TODO: Take a look a this when we have tools
                if event["event"] == "on_tool_start" or event["event"] == "on_tool_end":
                    inp = event.get("data", {}).get("input", {})
                    if isinstance(inp, dict):
                        query = inp.get("query", "")
                        effort = inp.get("research_effort", "")
                        content = f"{query} ({effort})" if effort else query
                    else:
                        content = str(inp)
                    yield {
                        "type": event["event"].removeprefix("on_"),
                        "name": event.get("name") or event.get("data", {}).get("name"),
                        "content": content or "",
                        "tool_call_id": event["run_id"],
                    }

                if event["event"] == "on_chat_model_stream":
                    chunk: AIMessageChunk = event["data"]["chunk"]
                    for text in _iter_stream_text(chunk.content):
                        yield text
        except Exception as exc:
            logging.exception("Doctor agent failed.")
            yield {
                "type": "error",
                "content": f"Doctor chat failed because the AI provider is temporarily unavailable: {exc}",
                "recoverable": True,
            }

    async def _call_research_agent(self, query: str, research_effort: ResearchEffort = "standard") -> str:
        if not self.user_id or not self.chat_session_id:
            return "I could not start research because the chat session is not available."

        if research_effort not in EFFORT_SETTINGS:
            research_effort = "standard"

        if os.getenv("IATREON_LOCAL_WORKER") == "1":
            from local_worker import store
            research_session_id = uuid.uuid4()
            research_report = ""
            citations = {}
            research_agent = ResearchAgent(None, research_session_id, effort=research_effort)
            async for research_chunk in research_agent.run(None, research_question=query, user_id=self.user_id):
                if isinstance(research_chunk, dict) and research_chunk.get("type") == "error":
                    return research_chunk.get("content") or "Research failed."
                if isinstance(research_chunk, tuple) and len(research_chunk) == 2:
                    research_report, citations = research_chunk
            store.save_research(
                self.user_id,
                str(research_session_id),
                str(self.chat_session_id),
                research_effort,
                research_report,
                citations,
                triggered_by="doctor",
            )
            return research_report or "No research report was produced."

        from db.db import unit_of_work
        from db.repositories import ResearchRepo

        research_repo = ResearchRepo(self.user_id)
        async with unit_of_work() as db:
            
            research_session = await research_repo.create_research_session(
                db,
                self.chat_session_id,
                triggered_by="doctor",
                research_effort=research_effort,
            )
            research_session_id = research_session.id

        research_report = ""
        citations = {}
        research_agent = ResearchAgent(research_repo, research_session_id, effort=research_effort)
        async for research_chunk in research_agent.run(None, research_question=query, user_id=self.user_id):
            if isinstance(research_chunk, dict) and research_chunk.get("type") == "error":
                return research_chunk.get("content") or "Research failed."
            if isinstance(research_chunk, tuple) and len(research_chunk) == 2:
                research_report, citations = research_chunk

        async with unit_of_work() as db:
            await research_repo.update_research_session(
                db,
                session_id=research_session_id,
                research_report=research_report,
                citations=citations,
            )

        return research_report or "No research report was produced."
            
