import asyncio
import logging
import re
from typing import Any, AsyncGenerator
from dotenv import load_dotenv
from uuid import UUID
import os
from typing import Literal

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import RunnableConfig
from langchain_core.tools import StructuredTool
from langchain_core.messages import AIMessageChunk

from agents.shared import create_agent_by_type, get_user_info, _iter_stream_text
from agents.inference import run_research_inference
from context.sources.openalex import OpenAlexClient
from db.schemas import ArticleData, BookSectionData, IntakeSessionData

from context.processing.pipeline import run_pipeline
from context.websearch import web_search, fetch_web_content
from context.sources.get_ncbi_books import BookshelfClient

load_dotenv()


ResearchEffort = Literal["fast", "standard", "deep", "web"]

EFFORT_SETTINGS = {
    "fast": {
        "temperature": 0.2,
        "model_env": "RESEARCH_AGENT_FAST_MODEL",
        "max_articles": 3,
        "web_results": 3,
        "openalex_results": 5,
        "prompt": "Be concise. Run only the searches needed to answer the focused clinical question.",
    },
    "standard": {
        "temperature": 0.7,
        "model_env": "RESEARCH_AGENT_MODEL",
        "max_articles": 5,
        "web_results": 5,
        "openalex_results": 10,
        "prompt": "Produce a comprehensive, citation-grounded report.",
    },
    "deep": {
        "temperature": 0.5,
        "model_env": "RESEARCH_AGENT_DEEP_MODEL",
        "max_articles": 8,
        "web_results": 8,
        "openalex_results": 15,
        "prompt": "Research deeply and check major guideline, review, and urgent-differential branches before finalizing.",
    },
    "web": {
        "temperature": 0.2,
        "model_env": "RESEARCH_AGENT_FAST_MODEL",
        "max_articles": 0,
        "web_results": 5,
        "openalex_results": 0,
        "prompt": "Use only web search and fetched web pages. Do not use literature, book, or OpenAlex searches.",
    },
}


def _as_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {
        key: item
        for key, item in vars(value).items()
        if not key.startswith("_")
    }


class ResearchAgent:
    def __init__(self, research_repo: Any | None, research_session_id: UUID, effort: ResearchEffort = "standard"):
        self.effort = effort if effort in EFFORT_SETTINGS else "standard"
        self.effort_settings = EFFORT_SETTINGS[self.effort]
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
        
        model_name = os.getenv(self.effort_settings["model_env"]) or os.getenv("RESEARCH_AGENT_MODEL")
        
        tools = [
            self.web_search_tool,
            self.fetch_web_content_tool,
        ]
        if self.effort != "web":
            tools.extend([
                self.search_medical_literature_tool,
                self.book_search_tool,
                self.openalex_search_tool,
            ])

        self.agent = create_agent_by_type("research", tools=tools,
                        checkpointer=self.checkpointer,
                        temperature=self.effort_settings["temperature"],
                        model_name=model_name)

        self.article_repo = None
        self.book_section_repo = None
        self.web_search_result_repo = None
        if not self._local_worker_mode():
            from db.repositories import ArticleRepo, BookSectionRepo, WebSearchResultRepo
            self.article_repo = ArticleRepo()
            self.book_section_repo = BookSectionRepo()
            self.web_search_result_repo = WebSearchResultRepo()

        self._citation_lookup: dict[int, dict] = {}
        self._citation_lock = asyncio.Lock()
        self._next_local_citation_num = 1
        self.source_warnings: list[str] = []

    def _local_worker_mode(self) -> bool:
        return os.getenv("IATREON_LOCAL_WORKER") == "1"

    def _reserve_local_citation_numbers(self, count: int) -> int:
        start = self._next_local_citation_num
        self._next_local_citation_num += count
        return start

    def _source_warning(self, provider: str, error: Exception) -> str:
        warning = f"{provider} unavailable: {error}"
        self.source_warnings.append(warning)
        logging.warning(warning)
        return warning
    
    async def _web_search(self, query: str) -> str:
        print(f"Performing web search for query: {query}")
        try:
            results = await asyncio.to_thread(web_search, query, self.effort_settings["web_results"])
        except Exception as exc:
            warning = self._source_warning("Web search", exc)
            return f"<source>\nWeb search results for query '{query}':\n{warning}\n</source>"

        if results and self._local_worker_mode():
            start = self._reserve_local_citation_numbers(len(results))
            for citation_num, result in enumerate(results, start=start):
                await self._record_local_citation(
                    citation_num,
                    "web_search_result",
                    title=result.get("title") or "",
                    query=query,
                    url=result.get("url") or "",
                    text="\n".join(result.get("highlights", [])),
                )
        elif results:
            from db.db import unit_of_work

            async with unit_of_work() as db:
                start = await self.research_repo.reserve_citation_numbers(db, self.session_id, len(results))
                for citation_num, result in enumerate(results, start=start):
                    db_result = await self.web_search_result_repo.upsert(
                        db=db,
                        query=query,
                        url=result["url"],
                        title=result.get("title"),
                        highlights="\n".join(result.get("highlights", [])),
                        full_content=None,
                    )
                    await self._record_citation(citation_num, "web_search_result", db_result, query=query)

        formatted_results = "\n\n".join(
            [
                f"- {r['title']} ({r['url']})\n" + "\n".join(r['highlights'])
                for r in results
            ]
        )
        return f"<source>\nWeb search results for query '{query}':\n{formatted_results}\n</source>"
    
    async def _fetch_web_content(self, url: str) -> str:
        print(f"Fetching content from URL: {url}")
        try:
            content = await asyncio.to_thread(fetch_web_content, url)
        except Exception as exc:
            content = self._source_warning("Web content fetch", exc)
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
        max_articles = min(max_articles, self.effort_settings["max_articles"])
        try:
            results = await run_pipeline(query, max_articles=max_articles, include_books=include_books)
        except Exception as exc:
            warning = self._source_warning("Medical literature search", exc)
            return f"<source>\nSearch results for query '{query}':\n{warning}\n</source>"

        self.source_warnings.extend(results.get("warnings", []))
        articles = results["articles"]
        books = results["books"]
        
        content = f"Search results for query: '{query}'\n\nArticles:\n"
        source_count = len(articles) + len(books)
        if source_count and self._local_worker_mode():
            start = self._reserve_local_citation_numbers(source_count)
            for i, article in enumerate(articles, start=start):
                content += f"[{i}] {article['title']} ({article['journal']}, {article['year']}, Citations: {article['citation_count']})\nAuthors: {', '.join(article['authors'])}\nAbstract: {article['abstract']}\n\n"
                await self._record_local_citation(
                    i,
                    "article",
                    title=article.get("title") or "",
                    query=query,
                    doi=article.get("doi") or "",
                    text="\n\n".join(part for part in [article.get("abstract"), article.get("full_text")] if part),
                    quality_score=article.get("quality_score", 0.0) or 0.0,
                )

            if books:
                content += f"Relevant Book Sections:\n"
                for i, book in enumerate(books, start + len(articles)):
                    content += f"[{i}] {book['title']}\nContent: {book['text']}\n\n"
                    await self._record_local_citation(
                        i,
                        "book_section",
                        title=book.get("title") or "",
                        query=query,
                        url=book.get("url") or "",
                        text=book.get("text") or "",
                    )
        elif source_count:
            from db.db import unit_of_work

            async with unit_of_work() as db:
                start = await self.research_repo.reserve_citation_numbers(db, self.session_id, source_count)
                for i, article in enumerate(articles, start=start):
                    content += f"[{i}] {article['title']} ({article['journal']}, {article['year']}, Citations: {article['citation_count']})\nAuthors: {', '.join(article['authors'])}\nAbstract: {article['abstract']}\n\n"
                    db_article = await self.article_repo.upsert(db, ArticleData(**_as_payload(article)))
                    await self._record_citation(
                        i,
                        "article",
                        db_article,
                        query=query,
                        quality_score=article.get("quality_score", 0.0) or 0.0,
                    )

                if books:
                    content += f"Relevant Book Sections:\n"
                    for i, book in enumerate(books, start + len(articles)):
                        content += f"[{i}] {book['title']}\nContent: {book['text']}\n\n"
                        db_section = await self.book_section_repo.upsert(db, BookSectionData(**_as_payload(book)))
                        await self._record_citation(i, "book_section", db_section, query=query)

        return "<source>\n" + content + "\n</source>"
    
    async def _book_search_tool(self, query: str) -> str:
        """Search for relevant book sections from NCBI Bookshelf based on a given query.
        
        Args:
            query (str): The search query to find relevant book sections.
        
        Returns:
            str: A formatted string containing the search results from NCBI Bookshelf.
        """
        
        book_client = BookshelfClient()
        try:
            books = await asyncio.to_thread(book_client.get_book_contents, query)
        except Exception as exc:
            warning = self._source_warning("NCBI Bookshelf", exc)
            return f"<source>\nBook search results for query '{query}':\n{warning}\n</source>"
        
        if books and self._local_worker_mode():
            start = self._reserve_local_citation_numbers(len(books))
            for i, book in enumerate(books, start=start):
                await self._record_local_citation(
                    i,
                    "book_section",
                    title=book.get("title") or "",
                    query=query,
                    url=book.get("url") or "",
                    text=book.get("text") or "",
                )
        elif books:
            from db.db import unit_of_work

            async with unit_of_work() as db:
                start = await self.research_repo.reserve_citation_numbers(db, self.session_id, len(books))
                for i, book in enumerate(books, start=start):
                    db_section = await self.book_section_repo.upsert(db, BookSectionData(**_as_payload(book)))
                    await self._record_citation(i, "book_section", db_section, query=query)
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
        try:
            articles = await open_alex_client.search_directly(
                query=query,
                max_results=self.effort_settings["openalex_results"],
                semantic=True,
            )
        except Exception as exc:
            warning = self._source_warning("OpenAlex", exc)
            return f"<source>\nOpenAlex search results for query '{query}':\n{warning}\n</source>"
        
        if articles and self._local_worker_mode():
            start = self._reserve_local_citation_numbers(len(articles))
            for i, article in enumerate(articles, start=start):
                await self._record_local_citation(
                    i,
                    "article",
                    title=article.title,
                    query=query,
                    doi=article.doi or "",
                    text="\n\n".join(part for part in [article.abstract, article.full_text] if part),
                    quality_score=article.quality_score or 0.0,
                )
        elif articles:
            from db.db import unit_of_work

            async with unit_of_work() as db:
                start = await self.research_repo.reserve_citation_numbers(db, self.session_id, len(articles))
                for i, article in enumerate(articles, start=start):
                    db_article = await self.article_repo.upsert(db, ArticleData(**_as_payload(article)))
                    await self._record_citation(
                        i,
                        "article",
                        db_article,
                        query=query,
                        quality_score=article.quality_score or 0.0,
                    )

        formatted_articles = "\n\n".join(
            [
                f"- {a.title} ({a.doi})\nAbstract: {a.abstract}" for a in articles
            ]
        )

        return f"<source>\nOpenAlex search results for query '{query}':\n{formatted_articles}\n</source>"
            
    def _extract_event_text(self, value) -> str:
        if value is None:
            return ""

        if isinstance(value, str):
            return value

        if isinstance(value, list):
            block_text = "".join(_iter_stream_text(value))
            if block_text:
                return block_text

            for item in reversed(value):
                text = self._extract_event_text(item)
                if text:
                    return text
            return ""

        if hasattr(value, "content"):
            return "".join(_iter_stream_text(value.content))

        if isinstance(value, dict):
            if "messages" in value and isinstance(value["messages"], list):
                for message in reversed(value["messages"]):
                    text = self._extract_event_text(message)
                    if text:
                        return text
                return ""

            for key in ("output", "content"):
                text = self._extract_event_text(value.get(key))
                if text:
                    return text

        return ""

    async def run(self, profile: IntakeSessionData | None = None, research_question: str | None = None, user_id: str | None = None) -> AsyncGenerator[dict | tuple[str, dict[int, dict]], None]:
        patient_profile = ""
        patient_case = ""
        inference_guidance = ""

        if profile:
            symptoms = ', '.join(s["name"] for s in profile.symptoms) if profile.symptoms else "None provided"
            red_flags = ', '.join(profile.red_flags) if profile.red_flags else "None provided"
            medical_summary = profile.medical_summary if profile.medical_summary else "None provided"

            patient_profile = await get_user_info(user_id=profile.user_id)
            inference_input = f"""Chief Complaint: {profile.chief_complaint}
Symptoms: {symptoms}
Red Flags: {red_flags}
Medical Summary: {medical_summary}
Research Question: {research_question or "General case research"}"""
        
            try:
                inference_guidance = await run_research_inference(inference_input)
            except Exception:
                logging.exception("Research inference failed; continuing without guidance.")

            patient_case = f"""# Patient Case:
Chief Complaint: {profile.chief_complaint}
Symptoms: {symptoms}
Red Flags: {red_flags}
Medical Summary: {medical_summary}"""


        elif user_id:
            patient_profile = await get_user_info(user_id=user_id)
 
        source_instruction = (
            "Use only web search and fetched web pages for insights related to the patient's chief complaint, symptoms, and red flags."
            if self.effort == "web"
            else "Use the tools at your disposal to search the web and medical literature for insights related to the patient's chief complaint, symptoms, and red flags."
        )

        user_message = f"""Given the following patient profile, perform research to gather relevant medical information. {source_instruction} Summarize your findings in a comprehensive report.

Prioritize urgent/emergent causes first when red flags are present. Normalize lay language into standard medical terminology and search both symptom-level and diagnosis-level queries. Clearly separate likely/common causes from urgent causes, and do not assume a definitive diagnosis.

{self.effort_settings["prompt"]}

{patient_profile}

{patient_case}
"""
        if research_question:
            user_message += f"\n# Research Request\n{research_question}\n"
        if inference_guidance:
            user_message += f"\n# Inference Guidance For Search Focus\n{inference_guidance}\n"
        messages = [{"role": "user", "content": user_message}]
        parts = []
        fallback_report = ""
        try:
            async for event in self.agent.astream_events({"messages": messages}, config=self.config, version="v2"):
                print(f"Received event: {event['event']}")
                if event["event"] == "on_chat_model_stream":
                    chunk: AIMessageChunk = event["data"]["chunk"]
                    for text in _iter_stream_text(chunk.content):
                        print(text, end="", flush=True)
                        parts.append(text)
                        yield {"type": "message", "content": text}

                if event["event"] in ["on_chat_model_end", "on_chain_end"]:
                    fallback_text = self._extract_event_text(event.get("data", {}))
                    if fallback_text:
                        fallback_report = fallback_text

                if event["event"] in ["on_tool_start", "on_tool_end"]:
                    print(event["run_id"])
                    # content = event["data"]["input"]["query"] if "query" in event["data"]["input"] else event["data"]["input"]["url"] if "url" in event["data"]["input"] else str(event["data"]["input"])
                    inp = event["data"].get("input", {})
                    content = inp.get("query") or inp.get("url") or str(inp)
                    yield {"type": event["event"].replace("on_", ""), "name": event["name"], "content": content, "tool_call_id": event["run_id"]}
        except Exception as exc:
            logging.exception("Research agent failed.")
            yield {
                "type": "error",
                "content": f"Research failed because the AI provider is temporarily unavailable: {exc}",
                "recoverable": True,
            }
            return

        final_message = "".join(parts) or fallback_report
        if not parts and final_message:
            print(final_message, end="", flush=True)
            # yield {"type": "message", "content": final_message}

        research_report = final_message if isinstance(final_message, str) else str(final_message)

        citations = await self.build_citation_manifest(research_report)

        yield (research_report, citations)
    
    
    async def _record_citation(
        self,
        citation_num: int,
        source_type: str,
        source: Any,
        query: str,
        quality_score: float | None = None,
    ) -> None:
        citation = {
            "citation_num": citation_num,
            "type": source_type,
            "id": str(source.id),
            "title": source.title,
            "query": query,
        }
        if source_type == "article":
            citation["doi"] = getattr(source, "doi", "")
            citation["quality_score"] = quality_score
        else:
            citation["url"] = getattr(source, "url", "")

        async with self._citation_lock:
            self._citation_lookup[citation_num] = citation

    async def _record_local_citation(
        self,
        citation_num: int,
        source_type: str,
        title: str,
        query: str,
        url: str = "",
        doi: str = "",
        text: str = "",
        quality_score: float | None = None,
    ) -> None:
        citation = {
            "citation_num": citation_num,
            "type": source_type,
            "id": f"local:{citation_num}",
            "title": title,
            "query": query,
            "url": url,
            "doi": doi,
            "text": text,
        }
        if quality_score is not None:
            citation["quality_score"] = quality_score
        async with self._citation_lock:
            self._citation_lookup[citation_num] = citation

    async def build_citation_manifest(self, content: str) -> dict[int, dict]:
        citation_pattern = r"\[(\d+)\]"
        matches = re.findall(citation_pattern, content)
        if not matches:
            return {}

        citation_manifest = {}
        seen_citations: set[int] = set()

        for match in matches:
            citation_num = int(match)
            if citation_num in seen_citations:
                continue

            citation = self._citation_lookup.get(citation_num)
            if citation is None:
                continue

            citation_manifest[citation_num] = citation
            seen_citations.add(citation_num)

        return citation_manifest
