import logging
from dotenv import load_dotenv

from langchain_core.tools import StructuredTool

from db.models import IntakeSession, ResearchSession
from db.db import SessionLocal
from db.repositories import ArticleRepo, BookSectionRepo, WebSearchResultRepo
from agents.shared import create_agent_by_type, web_search_tool


load_dotenv()


#TODO: proper system prompt; get_full_source tool
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
        
        self.agent = create_agent_by_type("diagnosis", tools=tools, system_prompt_format=system_prompt_format)
        self.intake_session = intake_session
        self.research_session = research_session
        

    async def _get_full_source(self, citation_id: int):
        async with SessionLocal() as db:
            source_info = self.research_session.citations.get(citation_id)
            
            if not source_info:
                return f"No source found for citation ID {citation_id}"
            
            source_type = source_info.get("type")
            source_id = source_info.get("id")
            
            #TODO: use the markdown util for sources 
            if source_type == "article":
                article = await ArticleRepo(db).get_article_by_id(source_id)
                if article:
                    return f"Title: {article.title}\nAbstract: {article.abstract}\n" + (f"Full Text: {article.full_text}" if article.full_text_available else "")
            
            elif source_type == "web_search_result":
                web_search_result = await WebSearchResultRepo(db).get_web_search_result_by_id(source_id)
                if web_search_result:
                    return f"Title: {web_search_result.title}\nURL: {web_search_result.url}\nHighlights: {web_search_result.highlights}\n"+ (f"Full Content:\n{web_search_result.full_content}" if web_search_result.full_content.strip() else "")
            
            elif source_type == "book_section":
                book_section = await BookSectionRepo(db).get_book_section_by_id(source_id)
                if book_section:
                    return f"Title: {book_section.title}\nContent: {book_section.text}"
            
            return f"No content found for source with citation ID {citation_id}"

    async def diagnose(self):
        logging.info("Starting diagnosis agent")
        user_message = f"""# Patient Information
    Chief complaint: {self.intake_session.chief_complaint or "N/A"}
    Medical Summary: {self.intake_session.medical_summary}"""
        if self.research_session and self.research_session.research_report:
            user_message += f"\n\n# Research Findings\n{self.research_session.research_report}"
        
        logging.debug(f"Diagnosis agent input message: {user_message}")
        
        response = await self.agent.ainvoke(user_message)
        return response["messages"][-1].content