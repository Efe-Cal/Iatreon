import json
import os
import re
from dotenv import load_dotenv

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langchain.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import RunnableConfig
from langchain_core.tools import StructuredTool

from db.models import IntakeSession, ResearchSession
from db.repositories import ArticleRepo, BookSectionRepo, ResearchRepo, WebSearchResultRepo
from db.schemas import ArticleData, ArticleData, BookSectionData, IntakeProfile

from context.processing.pipeline import run_pipeline
from context.websearch import web_search, fetch_web_content

load_dotenv()

with open(os.path.join(os.path.dirname(__file__), "prompts", "research_agent_system_prompt.txt")) as f:
    system_prompt = f.read()

class ResearchAgent:
    def __init__(self, db, research_repo: ResearchRepo, research_session: ResearchSession):
        self.model = ChatOpenAI(model="gemini-3-flash-preview",
                   base_url="https://ai.hackclub.com/proxy/v1",
                   api_key=os.getenv("HCAI_API_KEY"),
                   temperature=0.7)
        self.checkpointer = InMemorySaver()
        self.session_id = research_session.id
        self.config: RunnableConfig = {"configurable": {"thread_id": str(self.session_id)}}
        self.research_repo = research_repo
        
        self.web_search_tool = StructuredTool.from_function(
            coroutine=self._web_search,
            name="web_search",
            description=web_search.__doc__,
        )

        self.fetch_web_content_tool = StructuredTool.from_function(
            func=self._fetch_web_content,
            name="fetch_web_content",
            description=fetch_web_content.__doc__,
        )

        self.search_medical_literature_tool = StructuredTool.from_function(
            coroutine=self._search_medical_literature,
            name="search_medical_literature",
            description="Run the medical literature search with a given query.",
        )
        
        self.agent = create_agent(model=self.model,
                                  tools=[self.web_search_tool, self.fetch_web_content_tool, self.search_medical_literature_tool],
                                  system_prompt=system_prompt,
                                  checkpointer=self.checkpointer)

        self.db = db
        self.article_repo = ArticleRepo(self.db)
        self.book_section_repo = BookSectionRepo(self.db)
        self.web_search_result_repo = WebSearchResultRepo(self.db)
        
        self.citation_num = 0
    
    async def _web_search(self, query: str) -> str:
        print(f"Performing web search for query: {query}")
        results = web_search(query)
        for offset, result in enumerate(results, start=1):
            citation_num = self.citation_num + offset
            db_result = await self.web_search_result_repo.upsert(
                query=query,
                url=result["url"],
                title=result.get("title"),
                highlights="\n".join(result.get("highlights", [])),
                full_content=None,
            )
            await self.web_search_result_repo.link_to_session(
                session_id=self.session_id,
                web_search_result_id=db_result.id,
                citation_num=citation_num
            )
        self.citation_num += len(results)
        formatted_results = "\n\n".join(
            [
                f"- {r['title']} ({r['url']})\n" + "\n".join(r['highlights'])
                for r in results
            ]
        )
        return f"<source>\nWeb search results for query '{query}':\n{formatted_results}\n</source>"
    
    def _fetch_web_content(self, url: str) -> str:
        print(f"Fetching content from URL: {url}")
        content = fetch_web_content(url)
        return f"Fetched content from {url}:\n{content}"

    async def _search_medical_literature(self, query: str, max_articles: int = 5, include_books: bool = False) -> str:
        """
        Run the medical literature search with a given query.
        
        This function orchestrates the entire process of retrieving and processing medical literature based on the input query. It returns a structured dictionary containing the relevant articles and book sections.
        Sources include PubMed, PMC, OpenAlex, and NCBI Bookshelf.
        
        Args:
            query (str): The medical query to search for. This should be very concise (e.g., "chest pain diagnosis", "acute asthma exacerbation", etc.).
            max_articles (int): The maximum number of articles to retrieve and process.
            include_books (bool): Whether to include book sections from NCBI Bookshelf in the results.
        
        Returns:
            str: A formatted string containing the search results, including relevant articles and book sections.
        """
        print(f"Running medical literature search for query: {query}")
        results = await run_pipeline(query, max_articles=max_articles, include_books=include_books)
        articles = results["articles"]
        books = results["books"]

        content = f"Search results for query: '{query}'\n\nArticles:\n"
        for i, article in enumerate(articles, 1 + self.citation_num):
            content += f"[{i}] {article['title']} ({article['journal']}, {article['year']}, Citations: {article['citation_count']})\nAuthors: {', '.join(article['authors'])}\nAbstract: {article['abstract']}\n\n"
            db_article = await self.article_repo.upsert(ArticleData(**article))
            await self.article_repo.link_to_session(
                session_id=self.session_id,
                article_id=db_article.id,
                query=query,
                quality_score=article.get("quality_score", 0.0) or 0.0,
                citation_num=i
            )
            
        if books:
            content += f"Relevant Book Sections:\n"
            for i, book in enumerate(books, len(articles) + 1 + self.citation_num):
                content += f"[{i}] {book['title']}\nContent: {book['text']}\n\n"
                db_section = await self.book_section_repo.upsert(BookSectionData(**book))
                await self.book_section_repo.link_to_session(
                    session_id=self.session_id,
                    book_section_id=db_section.id,
                    query=query,
                    citation_num=i
                )

        self.citation_num += len(articles) + len(books)
        return "<source>\n" + content + "\n</source>"
    
    

    async def run(self, profile: IntakeSession) -> str:
        user_message = f"""Given the following patient profile, perform research to gather relevant medical information. Use the tools at your disposal to search the web and medical literature for insights related to the patient's chief complaint, symptoms, and red flags. Summarize your findings in a comprehensive report.
# Patient Profile
Chief Complaint: {profile.chief_complaint}
Symptoms: {', '.join(s["name"] for s in profile.symptoms)}
Red Flags: {', '.join(profile.red_flags)}
Medical Summary: {profile.medical_summary}
"""
        messages = [{"role": "user", "content": user_message}]
        response = await self.agent.ainvoke({"messages": messages}, config=self.config)
        
        return response["messages"][-1].content
    
    async def find_citation(self, content: str) -> str:
        CITATION_PATTERN = r"\[(\d+)\]"
        matches = re.findall(CITATION_PATTERN, content)
        
        if matches:
            sources = await self.research_repo.get_all_session_sources(session_id=self.session_id)
            print(matches)
            all_sources = sources["articles"] + sources["book_sections"] + sources["web_search_results"]
            sources_dict = {s[1]: s[0] for s in all_sources}
            print(f"Sources dict: {json.dumps(sources_dict, indent=2, default=str)}")
            cited_sources = []
            for match in matches:
                citation_num = int(match)
                if citation_num in sources_dict:
                    cited_sources.append(sources_dict[citation_num])

            print(f"Cited sources: {cited_sources}")
            return cited_sources
                    