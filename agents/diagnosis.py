import logging
from dotenv import load_dotenv

from langchain_core.tools import StructuredTool

from db.models import IntakeSession, ResearchSession
from db.db import read_only_session
from db.repositories import ArticleRepo, BookSectionRepo, IntakeRepo, ResearchRepo, WebSearchResultRepo
from agents.shared import create_agent_by_type, get_user_info, web_search_tool
from db.schemas import DiagnosisReport

load_dotenv()

#TODO: (importance: HIGH) diagnosis agent should have a request_reseach tool instead of web_search, which would trigger a subset of the research agent (?), properly handling the sources and stuff

#TODO: (importance: HIGH-) proper system prompt
class DiagnosisAgent():
    def __init__(self, intake_session: IntakeSession, research_session: ResearchSession | None):
        
        self.get_full_source_tool = StructuredTool.from_function(
            func=self._get_full_source,
            name="get_full_source",
            description="Use this tool to retrieve the full content of a source based on its citation ID. The input should be the citation ID as an integer."
        )
        
        tools = [web_search_tool]
        if research_session:
            tools.append(self.get_full_source_tool)
        
        system_prompt_format = {}
        system_prompt_format["inst_research_sources"] = "Analyze any relevant research findings that may provide insights into the patient's condition.\n    - IF you are provided with research findings, you may call the `get_full_source` tool to retrieve the full content of any research findings if necessary.\n    - " if research_session else ""
        system_prompt_format["get_full_source_tool_expl"] = """- `get_full_source`: Retrieve the full content of a research finding, if any is provided.
  - Input parameters: `citation_id` (the citation number of the research finding, as provided in the research report's References section)
  - Output: The full content of the research finding's source\n""" if research_session else ""
        
        self.agent = create_agent_by_type("diagnosis", 
                                          tools=tools, 
                                          system_prompt_format=system_prompt_format,
                                          response_format=DiagnosisReport)

        self.intake_session = intake_session
        self.research_session = research_session
        
        self.user_id = intake_session.user_id
        

    async def _get_full_source(self, citation_id: int):
        async with read_only_session() as db:
            source_info = self.research_session.citations.get(citation_id)
            
            if not source_info:
                return f"No source found for citation ID {citation_id}"
            
            source_type = source_info.get("type")
            source_id = source_info.get("id")
            
            #TODO: use the markdown util for sources 
            if source_type == "article":
                article = await ArticleRepo().get_article_by_id(db, source_id)
                if article:
                    return f"Title: {article.title}\nAbstract: {article.abstract}\n" + (f"Full Text: {article.full_text}" if article.full_text_available else "")
            
            elif source_type == "web_search_result":
                web_search_result = await WebSearchResultRepo().get_web_search_result_by_id(db, source_id)
                if web_search_result:
                    return f"Title: {web_search_result.title}\nURL: {web_search_result.url}\nHighlights: {web_search_result.highlights}\n"+ (f"Full Content:\n{web_search_result.full_content}" if web_search_result.full_content.strip() else "")
            
            elif source_type == "book_section":
                book_section = await BookSectionRepo().get_book_section_by_id(db, source_id)
                if book_section:
                    return f"Title: {book_section.title}\nContent: {book_section.text}"
            
            return f"No content found for source with citation ID {citation_id}"

    async def diagnose(self):
        logging.info("Starting diagnosis agent")
        
        patient_info = await get_user_info(user_id=self.user_id)
        
        user_message = f"""Given the following patient profile and any relevant research findings, provide a detailed diagnosis and potential conditions that may explain the patient's symptoms. Include a rationale for your diagnosis and any recommended next steps for further evaluation or treatment.

{patient_info}
        
# Patient Case
Chief complaint: {self.intake_session.chief_complaint or "N/A"}
Symptoms: {', '.join(self.intake_session.symptoms) if self.intake_session.symptoms else "N/A"}
Medical Summary: {self.intake_session.medical_summary}"""
        if self.research_session and self.research_session.research_report:
            user_message += f"\n\n# Research Findings\n{self.research_session.research_report}"
        
        logging.debug(f"Diagnosis agent input message: {user_message}")
        
        response = await self.agent.ainvoke(user_message)
        print(response["structured_response"])
        return response["messages"][-1].content
    

if __name__ == "__main__":
    import asyncio
    from uuid import UUID
    
    async def main():
        # Example usage
        intake_session_id = UUID("your-intake-session-uuid-here")
        research_session_id = UUID("your-research-session-uuid-here")  # Optional, can be None
        
        async with read_only_session() as db:
            intake_session = await IntakeRepo().get_session(db, intake_session_id)
            research_session = await ResearchRepo().get_research_session(db, research_session_id) if research_session_id else None
            
            diagnosis_agent = DiagnosisAgent(intake_session, research_session)
            diagnosis_report = await diagnosis_agent.diagnose()
            print(diagnosis_report)
    
    asyncio.run(main())