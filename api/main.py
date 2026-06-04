from collections.abc import AsyncIterable, Iterable

from fastapi import FastAPI
from fastapi.sse import EventSourceResponse
from pydantic import BaseModel

from agents.intake import run_intake_cli
from agents.research import ResearchAgent

from db.db import SessionLocal
from db.repositories import IntakeRepo, ResearchRepo

app = FastAPI()

class ChatRequest(BaseModel):
    agent_type: str
    message: str

@app.post("/chat", response_class=EventSourceResponse)
async def stream_chat(chat_request: ChatRequest) -> AsyncIterable:
    if chat_request.agent_type == "intake":
        yield run_intake_cli(chat_request.message)
    else:
        return {"error": "Unsupported agent type"}
    
@app.post("/research", response_class=EventSourceResponse)
async def stream_research(intake_id: str) -> AsyncIterable:
    async with SessionLocal() as session:
        research_repo = ResearchRepo(session)
        intake_session = await IntakeRepo(session).get_session(intake_id)
        if not intake_session:
            yield "Error: Intake session not found."
            return

        research_session = await research_repo.create_research_session(intake_session.user_id, intake_session.id)
        research_agent = ResearchAgent(session, research_repo, research_session.id)
        async for research_chunk in research_agent.run(intake_session):
            if isinstance(research_chunk, str):
                yield research_chunk

            elif isinstance(research_chunk, tuple) and len(research_chunk) == 2:
                research_report, citations = research_chunk
                await research_repo.update_research_session(
                    session_id=research_session.id,
                    research_report=research_report,
                    citations=citations,
                )
