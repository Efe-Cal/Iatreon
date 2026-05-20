import os
import re
from dotenv import load_dotenv

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import RunnableConfig
from langchain_core.tools import StructuredTool

from db.models import Article, BookSection, IntakeSession, ResearchSession, WebSearchResult
from db.repositories import ArticleRepo, BookSectionRepo, ResearchRepo, WebSearchResultRepo
from db.schemas import ArticleData, BookSectionData

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
        final_message = response["messages"][-1].content
        research_report = final_message if isinstance(final_message, str) else str(final_message)
        citations = await self.build_citation_manifest(research_report)

        await self.research_repo.update_research_session(
            session_id=self.session_id,
            research_report=research_report,
            citations=citations,
        )

        return research_report
    
    
    async def _get_citation_lookup(self) -> dict[int, tuple[str, Article | BookSection | WebSearchResult]]:
        sources = await self.research_repo.get_all_session_sources(session_id=self.session_id)
        lookup: dict[int, tuple[str, Article | BookSection | WebSearchResult]] = {}

        for source_type, source_rows in sources.items():
            for source, citation_num in source_rows:
                if citation_num is None:
                    continue
                lookup[int(citation_num)] = (source_type, source)

        return lookup

    def _serialize_citation(self, citation_num: int, source_type: str, source: Article | BookSection | WebSearchResult) -> dict:
        if source_type == "articles":
            return {
                "citation_num": citation_num,
                "source_type": source_type,
                "source_id": str(source.id),
                "title": source.title,
                "doi": source.doi,
            }

        if source_type == "book_sections":
            return {
                "citation_num": citation_num,
                "source_type": source_type,
                "source_id": str(source.id),
                "title": source.title,
                "url": source.url,
            }

        return {
            "citation_num": citation_num,
            "source_type": source_type,
            "source_id": str(source.id),
            "title": source.title,
            "url": source.url,
        }

    async def build_citation_manifest(self, content: str) -> dict[int, dict]:
        citation_pattern = r"\[(\d+)\]"
        matches = re.findall(citation_pattern, content)
        if not matches:
            return {}

        citation_lookup = await self._get_citation_lookup()
        citation_manifest = {}
        seen_citations: set[int] = set()

        for match in matches:
            citation_num = int(match)
            if citation_num in seen_citations:
                continue

            lookup_entry = citation_lookup.get(citation_num)
            if lookup_entry is None:
                continue

            source_type, source = lookup_entry
            citation_manifest[citation_num] = self._serialize_citation(citation_num, source_type, source)
            seen_citations.add(citation_num)

        return citation_manifest

    async def find_citation(self, content: str) -> dict[int, Article | BookSection | WebSearchResult]:
        citation_pattern = r"\[(\d+)\]"
        matches = re.findall(citation_pattern, content)

        if not matches:
            return {}

        citation_lookup = await self._get_citation_lookup()
        cited_sources: dict[int, Article | BookSection | WebSearchResult] = {}
        seen_citations: set[int] = set()

        for match in matches:
            citation_num = int(match)
            if citation_num in seen_citations:
                continue

            lookup_entry = citation_lookup.get(citation_num)
            if lookup_entry is None:
                continue

            cited_sources[citation_num] = lookup_entry[1]
            seen_citations.add(citation_num)

        return cited_sources
                    