from collections.abc import AsyncIterable

from fastapi import FastAPI, HTTPException, Request
from fastapi.sse import EventSourceResponse

from pydantic import BaseModel

from agents.intake import run_intake_cli
from agents.research import ResearchAgent
from agents.diagnosis import DiagnosisAgent

from db.db import SessionLocal
from db.models import IntakeSession, ResearchSession
from db.repositories import IntakeRepo, ResearchRepo
from db.schemas import IntakeProfile

app = FastAPI()

class ChatRequest(BaseModel):
    message: str
    conversation_id: str

def get_user_id_or_400(request: Request) -> str:
    user_id = request.headers.get("X-User-ID", None)
    if not user_id:
        raise HTTPException(status_code=400, detail="X-User-ID header missing")
    return user_id

@app.post("/chat/intake", response_class=EventSourceResponse)
async def stream_intake_chat(chat_request: ChatRequest, request: Request) -> AsyncIterable:
    user_id = get_user_id_or_400(request)
    
    async with SessionLocal() as session:
        intake_repo = IntakeRepo(session, user_id)
        intake_session: IntakeSession = await intake_repo.create_session()
        async for chunk in run_intake_cli(chat_request.message, chat_request.conversation_id):

            if isinstance(chunk, tuple) and len(chunk) == 2 and isinstance(chunk[0], IntakeProfile):
                await intake_repo.update_session(intake_session.id, profile=chunk[0], transcript=chunk[1])
                await intake_repo.complete_session(intake_session.id)
                yield {"type": "intake_complete", "profile": chunk[0], "transcript": chunk[1]}
            else:
                yield {"type": "message", "content": chunk}
                
@app.post("/research", response_class=EventSourceResponse)
async def stream_research(intake_id: str, request: Request) -> AsyncIterable:
    user_id = get_user_id_or_400(request)
    async with SessionLocal() as session:
        research_repo = ResearchRepo(session, user_id)
        intake_session: IntakeSession = await IntakeRepo(session, user_id).get_session(intake_id)

        if not intake_session:
            yield "Error: Intake session not found."
            return
        
        research_session: ResearchSession = await research_repo.create_research_session(intake_session.id)
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


@app.post("/diagnose")
async def stream_diagnosis(intake_id: str, request: Request) -> AsyncIterable:
    user_id = get_user_id_or_400(request)
    async with SessionLocal() as session:
        intake_session: IntakeSession = await IntakeRepo(session, user_id).get_session(intake_id)
        if not intake_session:
            yield "Error: Intake session not found."
            return
        if intake_session.user_id != user_id:
            yield "Error: Unauthorized."
        
        research_session = await ResearchRepo(session, user_id).get_research_session_by_intake_id(intake_session.id)
        diagnosis_agent = DiagnosisAgent(intake_session, research_session)
        async for diagnosis_chunk in diagnosis_agent.diagnose():
            yield diagnosis_chunk