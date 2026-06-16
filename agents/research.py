import asyncio
import re
from typing import AsyncGenerator
from dotenv import load_dotenv
from uuid import UUID

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import RunnableConfig
from langchain_core.tools import StructuredTool
from langchain_core.messages import AIMessageChunk

from agents.shared import create_agent_by_type, get_user_info
from context.sources.openalex import OpenAlexClient
from db.models import Article, BookSection, IntakeSession, ResearchSession, WebSearchResult
from db.repositories import ArticleRepo, BookSectionRepo, ResearchRepo, WebSearchResultRepo
from db.schemas import ArticleData, BookSectionData
from db.db import unit_of_work, read_only_session

from context.processing.pipeline import run_pipeline
from context.websearch import web_search, fetch_web_content
from context.sources.get_ncbi_books import BookshelfClient

load_dotenv()


#TODO: Have another agent (inference) guess some probable diseases based on the profile then use that in research agent
#TODO ^^ Maybe run diagnosis agent with a fast model as a middle step
#TODO: Have "research effort" that changes the prompt (tell the model to be fast) and the model tier 
class ResearchAgent:
    def __init__(self, research_repo: ResearchRepo, research_session_id: UUID):
        self.checkpointer = InMemorySaver()
        self.session_id = research_session_id
        self.config: RunnableConfig = {"configurable": {"thread_id": str(self.session_id)}}
        self.research_repo = research_repo
        
        self.web_search_tool = StructuredTool.from_function(
            coroutine=self._web_search,
            name="web_search",
            description=web_search.__doc__,
        )

        self.fetch_web_content_tool = StructuredTool.from_function(
            coroutine=self._fetch_web_content,
            name="fetch_web_content",
            description=fetch_web_content.__doc__,
        )

        self.search_medical_literature_tool = StructuredTool.from_function(
            coroutine=self._search_medical_literature,
            name="search_medical_literature",
        )
        
        self.book_search_tool = StructuredTool.from_function(
            coroutine=self._book_search_tool,
            name="book_search"
        )
        
        self.openalex_search_tool = StructuredTool.from_function(
            coroutine=self.openalex_search,
            name="openalex_search"
        )
        
        self.agent = create_agent_by_type("research", tools=[
            self.web_search_tool,
            self.fetch_web_content_tool,
            self.search_medical_literature_tool,
            self.book_search_tool,
            self.openalex_search_tool],
                                          checkpointer=self.checkpointer)

        self.article_repo = ArticleRepo()
        self.book_section_repo = BookSectionRepo()
        self.web_search_result_repo = WebSearchResultRepo()

        #TODO: DB-assigned sequence: make citation_num an auto-increment per research_session_id
        self.citation_num = 0
        self._citation_lock = asyncio.Lock()
    
    async def _web_search(self, query: str) -> str:
        print(f"Performing web search for query: {query}")
        results = await asyncio.to_thread(web_search, query)

        async with self._citation_lock:
            start = self.citation_num + 1
            self.citation_num += len(results)

        async with unit_of_work() as db:
            for citation_num, result in enumerate(results, start=start):
                db_result = await self.web_search_result_repo.upsert(
                    db=db,
                    query=query,
                    url=result["url"],
                    title=result.get("title"),
                    highlights="\n".join(result.get("highlights", [])),
                    full_content=None,
                )
                await self.web_search_result_repo.link_to_session(
                    db=db,
                    session_id=self.session_id,
                    web_search_result_id=db_result.id,
                    citation_num=citation_num
                )

        formatted_results = "\n\n".join(
            [
                f"- {r['title']} ({r['url']})\n" + "\n".join(r['highlights'])
                for r in results
            ]
        )
        return f"<source>\nWeb search results for query '{query}':\n{formatted_results}\n</source>"
    
    async def _fetch_web_content(self, url: str) -> str:
        print(f"Fetching content from URL: {url}")
        content = await asyncio.to_thread(fetch_web_content, url)
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
        # print(f"Running medical literature search for query: {query}")
        results = await run_pipeline(query, max_articles=max_articles, include_books=include_books)
        articles = results["articles"]
        books = results["books"]

        async with self._citation_lock:
            start = self.citation_num + 1
            self.citation_num += len(articles) + len(books)
        
        content = f"Search results for query: '{query}'\n\nArticles:\n"
        async with unit_of_work() as db:
            for i, article in enumerate(articles, start=start):
                content += f"[{i}] {article['title']} ({article['journal']}, {article['year']}, Citations: {article['citation_count']})\nAuthors: {', '.join(article['authors'])}\nAbstract: {article['abstract']}\n\n"
                db_article = await self.article_repo.upsert(db, ArticleData(**article))
                await self.article_repo.link_to_session(
                    db=db,
                    session_id=self.session_id,
                    article_id=db_article.id,
                    query=query,
                    quality_score=article.get("quality_score", 0.0) or 0.0,
                    citation_num=i
                )

            if books:
                content += f"Relevant Book Sections:\n"
                for i, book in enumerate(books, start + len(articles)):
                    content += f"[{i}] {book['title']}\nContent: {book['text']}\n\n"
                    db_section = await self.book_section_repo.upsert(db, BookSectionData(**book))
                    await self.book_section_repo.link_to_session(
                        db=db,
                        session_id=self.session_id,
                        book_section_id=db_section.id,
                        query=query,
                        citation_num=i
                    )

        return "<source>\n" + content + "\n</source>"
    
    async def _book_search_tool(self, query: str) -> str:
        """Search for relevant book sections from NCBI Bookshelf based on a given query.
        
        Args:
            query (str): The search query to find relevant book sections.
        
        Returns:
            str: A formatted string containing the search results from NCBI Bookshelf.
        """
        
        book_client = BookshelfClient()
        books = await book_client.get_book_contents(query)
        
        async with self._citation_lock:
            start = self.citation_num + 1
            self.citation_num += len(books)
        
        async with unit_of_work() as db:
            for i, book in enumerate(books, start=start):
                db_section = await self.book_section_repo.upsert(db, BookSectionData(**book))
                await self.book_section_repo.link_to_session(
                    db=db,
                    session_id=self.session_id,
                    book_section_id=db_section.id,
                    query=query,
                    citation_num=i
                )
        formatted_books = "\n\n".join(
            [
                f"- {b['title']} ({b['url']})\nContent: {b['text']}..." for b in books
            ]
        )
        return f"<source>\nBook search results for query '{query}':\n{formatted_books}\n</source>"
            
    async def openalex_search(self, query: str) -> str:
        """
        Perform a semantic search using the OpenAlex API for the given query.
        
        Args:
            query (str): The search query to be sent to the OpenAlex API, which **should be a longer than a typical keyword search and more of a natural language query**
        
        Returns:
            str: A formatted string containing the search results from OpenAlex.
        """
        open_alex_client = OpenAlexClient()
        articles = await open_alex_client.search_directly(query=query, semantic=True)

        with self._citation_lock:
            start = self.citation_num + 1
            self.citation_num += len(articles)
        
        async with unit_of_work() as db:
            for i, article in enumerate(articles, start=start):
                db_article = await self.article_repo.upsert(db, article)
                await self.article_repo.link_to_session(
                    db=db,
                    session_id=self.session_id,
                    article_id=db_article.id,
                    query=query,
                    quality_score=article.quality_score or 0.0,
                    citation_num=i
                )

        formatted_articles = "\n\n".join(
            [
                f"- {a.title} ({a.doi})\nAbstract: {a.abstract}" for a in articles
            ]
        )

        return f"<source>\nOpenAlex search results for query '{query}':\n{formatted_articles}\n</source>"
            
    async def run(self, profile: IntakeSession) -> AsyncGenerator[dict | tuple[str, dict[int, dict]], None]:
        symptoms = ', '.join(s["name"] for s in profile.symptoms) if profile.symptoms else "None provided"
        red_flags = ', '.join(profile.red_flags) if profile.red_flags else "None provided"
        medical_summary = profile.medical_summary if profile.medical_summary else "None provided"

        patient_profile = await get_user_info(user_id=profile.user_id)
        
        user_message = f"""Given the following patient profile, perform research to gather relevant medical information. Use the tools at your disposal to search the web and medical literature for insights related to the patient's chief complaint, symptoms, and red flags. Summarize your findings in a comprehensive report.

Prioritize urgent/emergent causes first when red flags are present. Normalize lay language into standard medical terminology and search both symptom-level and diagnosis-level queries. Clearly separate likely/common causes from urgent causes, and do not assume a definitive diagnosis.

Produce a comprehensive, citation-grounded report

{patient_profile}

# Patient Case:
Chief Complaint: {profile.chief_complaint}
Symptoms: {symptoms}
Red Flags: {red_flags}
Medical Summary: {medical_summary}
"""
        messages = [{"role": "user", "content": user_message}]
        parts = []
        async for event in self.agent.astream_events({"messages": messages}, config=self.config, version="v2"):
            print(f"Received event: {event['event']}")
            if event["event"] == "on_chat_model_stream":
                chunk: AIMessageChunk = event["data"]["chunk"]
                # print(f"Received chunk: {chunk.content}")
                if chunk.content:
                    if isinstance(chunk.content, str):
                        print(chunk.content, end="", flush=True)
                        parts.append(chunk.content)
                    elif isinstance(chunk.content, list):
                        for block in chunk.content:
                            print(f"Processing block: {block}")
                            if block["type"] == "text":
                                text = block["text"]
                                print(text, end="", flush=True)
                                parts.append(text)
                                yield {"type": "message", "content": text}
                    
            if event["event"] in ["on_tool_start", "on_tool_end"]:
                print(event["run_id"])
                # content = event["data"]["input"]["query"] if "query" in event["data"]["input"] else event["data"]["input"]["url"] if "url" in event["data"]["input"] else str(event["data"]["input"])
                inp = event["data"].get("input", {})
                content = inp.get("query") or inp.get("url") or str(inp)
                yield {"type": event["event"].replace("on_", ""), "name": event["name"], "content": content, "tool_call_id": event["run_id"]}

        final_message = "".join(parts)
        
        research_report = final_message if isinstance(final_message, str) else str(final_message)
        
        citations = await self.build_citation_manifest(research_report)

        yield (research_report, citations)
    
    
    async def _get_citation_lookup(self) -> dict[int, tuple[str, Article | BookSection | WebSearchResult]]:
        async with read_only_session() as db:
            sources = await self.research_repo.get_all_session_sources(db=db, session_id=self.session_id)
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

