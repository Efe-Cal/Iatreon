import logging
import os
from dotenv import load_dotenv
from uuid import UUID, uuid4

from langchain_core.tools import StructuredTool

from agents.research import ResearchAgent
from agents.shared import create_agent_by_type, get_user_info
from db.schemas import DiagnosisReport, IntakeSessionData, ResearchSessionData

load_dotenv()

class DiagnosisAgent():
    def __init__(self, intake_session: IntakeSessionData, research_session: ResearchSessionData | None, chat_session_id: UUID | None = None):
        self.intake_session = intake_session
        self.research_session = research_session
        self.chat_session_id = chat_session_id
        self.user_id = intake_session.user_id
        self.research_repo = None
        
        self.get_full_source_tool = StructuredTool.from_function(
            func=self._get_full_source,
            name="get_full_source",
            description="Use this tool to retrieve the full content of a source based on its citation ID. The input should be the citation ID as an integer."
        )
        self.request_research_tool = StructuredTool.from_function(
            coroutine=self._request_research,
            name="request_research",
            description="Request focused medical research for a clinical question. Input should be a concise research question."
        )
        
        tools = [self.request_research_tool, self.get_full_source_tool]
        
        system_prompt_format = {}
        system_prompt_format["inst_research_sources"] = "Analyze any relevant research findings that may provide insights into the patient's condition.\n    - IF you need more evidence, call `request_research` with a focused clinical question.\n    - IF you are provided with research findings, you may call the `get_full_source` tool to retrieve the full content of any research findings if necessary.\n    - "
        system_prompt_format["get_full_source_tool_expl"] = """- `request_research`: Request focused medical research for a clinical question and save the resulting citations.
  - Input parameters: `research_question` (a concise clinical research question)
  - Output: A citation-grounded research report
- `get_full_source`: Retrieve the full content of a research finding, if any is provided.
  - Input parameters: `citation_id` (the citation number of the research finding, as provided in the research report's References section)
  - Output: The full content of the research finding's source\n"""
        
        self.agent = create_agent_by_type("diagnosis", 
                                          tools=tools, 
                                          system_prompt_format=system_prompt_format,
                                          response_format=DiagnosisReport)
        

    async def _request_research(self, research_question: str) -> str:
        if os.getenv("IATREON_LOCAL_WORKER") == "1":
            from local_worker import store
            research_session_id = uuid4()
            research_report = ""
            citations = {}
            research_agent = ResearchAgent(None, research_session_id, effort="fast")
            async for research_chunk in research_agent.run(self.intake_session, research_question=research_question):
                if isinstance(research_chunk, dict) and research_chunk.get("type") == "error":
                    return research_chunk.get("content") or "Research failed."
                if isinstance(research_chunk, tuple) and len(research_chunk) == 2:
                    research_report, citations = research_chunk
            store.save_research(
                str(self.user_id),
                str(research_session_id),
                str(self.chat_session_id) if self.chat_session_id else None,
                "fast",
                research_report,
                citations,
                triggered_by="diagnosis",
            )
            return research_report or "No research report was produced."

        from db.db import unit_of_work
        from db.repositories import ResearchRepo

        self.research_repo = ResearchRepo(str(self.user_id))
        async with unit_of_work() as db:
            research_session = await self.research_repo.create_research_session(
                db,
                self.chat_session_id,
                triggered_by="diagnosis",
                research_effort="fast",
            )
            research_session_id = research_session.id

        research_report = ""
        citations = {}
        research_agent = ResearchAgent(self.research_repo, research_session_id, effort="fast")
        async for research_chunk in research_agent.run(self.intake_session, research_question=research_question):
            if isinstance(research_chunk, dict) and research_chunk.get("type") == "error":
                return research_chunk.get("content") or "Research failed."
            if isinstance(research_chunk, tuple) and len(research_chunk) == 2:
                research_report, citations = research_chunk

        async with unit_of_work() as db:
            updated = await self.research_repo.update_research_session(
                db,
                session_id=research_session_id,
                research_report=research_report,
                citations=citations,
            )
            if updated:
                self.research_session = updated

        return research_report or "No research report was produced."

    async def _get_full_source(self, citation_id: int):
        if not self.research_session:
            return f"No source found for citation ID {citation_id}"

        if os.getenv("IATREON_LOCAL_WORKER") == "1":
            source_info = self.research_session.citations.get(citation_id) or self.research_session.citations.get(str(citation_id))
            if source_info and source_info.get("text"):
                return source_info["text"]
            return f"No content found for source with citation ID {citation_id}"

        from db.db import read_only_session
        from db.repositories import ArticleRepo, BookSectionRepo, WebSearchResultRepo

        async with read_only_session() as db:
            source_info = self.research_session.citations.get(citation_id) or self.research_session.citations.get(str(citation_id))
            
            if not source_info:
                return f"No source found for citation ID {citation_id}"
            
            source_type = source_info.get("type")
            source_id = UUID(str(source_info.get("id")))
            
            if source_type == "article":
                article = await ArticleRepo().get_article_by_id(db, source_id)
                if article:
                    return f"Title: {article.title}\nAbstract: {article.abstract}\n" + (f"Full Text: {article.full_text}" if article.full_text_available else "")
            
            elif source_type == "web_search_result":
                web_search_result = await WebSearchResultRepo().get_web_search_result_by_id(db, source_id)
                if web_search_result:
                    full_content = web_search_result.full_content or ""
                    return f"Title: {web_search_result.title}\nURL: {web_search_result.url}\nHighlights: {web_search_result.highlights}\n"+ (f"Full Content:\n{full_content}" if full_content.strip() else "")
            
            elif source_type == "book_section":
                book_section = await BookSectionRepo().get_book_section_by_id(db, source_id)
                if book_section:
                    return f"Title: {book_section.title}\nContent: {book_section.text}"
            
            return f"No content found for source with citation ID {citation_id}"

    async def diagnose(self):
        logging.info("Starting diagnosis agent")
        
        patient_info = await get_user_info(user_id=self.user_id)
        
        symptoms = ', '.join(
            symptom.get("name", str(symptom)) if isinstance(symptom, dict) else str(symptom)
            for symptom in self.intake_session.symptoms
        ) if self.intake_session.symptoms else "N/A"

        user_message = f"""Given the following patient profile and any relevant research findings, provide a detailed diagnosis and potential conditions that may explain the patient's symptoms. Include a rationale for your diagnosis and any recommended next steps for further evaluation or treatment.

{patient_info}
        
# Patient Case
Chief complaint: {self.intake_session.chief_complaint or "N/A"}
Symptoms: {symptoms}
Medical Summary: {self.intake_session.medical_summary}"""
        if self.research_session and self.research_session.research_report:
            user_message += f"\n\n# Research Findings\n{self.research_session.research_report}"
        
        logging.debug(f"Diagnosis agent input message: {user_message}")
        
        try:
            response = await self.agent.ainvoke({"messages": [{"role": "user", "content": user_message}]}, version="v2")
            report = response.value["structured_response"]
            yield report.model_dump() if hasattr(report, "model_dump") else report or response["messages"][-1].content
        except Exception as exc:
            logging.exception("Diagnosis agent failed.")
            yield {
                "type": "error",
                "content": f"Diagnosis failed because the AI provider is temporarily unavailable: {exc}",
                "recoverable": True,
            }
    
