import json
from dataclasses import asdict
import re
import unicodedata

from .pdf_utils import PDFClient
from ..models import Article, BookSection
from ..sources.openalex import OpenAlexClient
from ..sources.pmc import PMCClient
from ..sources.pubmed import PubMedClient
from .ranking import QualityRanker
from ..sources.get_ncbi_books import BookshelfClient


class MedicalKnowledgePipeline:
    def __init__(self):
        self.pubmed = PubMedClient()
        self.pmc = PMCClient()
        self.openalex = OpenAlexClient()
        self.bookshelf = BookshelfClient()
        self.ranker = QualityRanker()
        self.pdf_client = PDFClient()

    async def search(self, query: str, max_results: int = 10, include_books: bool = True) -> dict:
        # print(f"\n{'='*60}")
        # print(f"MEDICAL PIPELINE — Query: '{query}'")
        # print(f"{'='*60}")

        pubmed_ids = self.pubmed.search(query, max_results=max_results)
        articles = self.pubmed.fetch_abstracts(pubmed_ids)

        for article in articles:
            article.source = "PubMed Abstract"

        articles = self.pmc.enrich_articles_with_fulltext(articles)
        articles = self.openalex.enrich_articles(articles)
        for article in articles:
            if not article.full_text_available and article.pdf_url:
                article.full_text = await self.pdf_client.get_pdf_content(article.pdf_url)
                article.full_text_available = bool(article.full_text)

        openalex_articles = await self.openalex.search_directly(query, max_results=int(max_results*0.6))
        articles.extend(openalex_articles)

        books = []
        if include_books:
            books = self.bookshelf.get_book_contents(query, num_results=3)

        articles = self.ranker.rank(articles)

        full_text_count = sum(1 for a in articles if a.full_text_available)
        pdf_count = sum(1 for a in articles if a.pdf_url and not a.full_text_available)
        abstract_count = len(articles) - full_text_count - pdf_count

        # print(f"\n{'='*60}")
        # print("RESULTS SUMMARY")
        # print(f"  Total articles : {len(articles)}")
        # print(f"  Full text (PMC): {full_text_count}")
        # print(f"  PDF links (OA) : {pdf_count}")
        # print(f"  Abstract only  : {abstract_count}")
        # print(f"  Book sections  : {len(books)}")
        # print(f"{'='*60}\n")

        return {
            "query": query,
            "articles": articles,
            "books": books,
        }

    async def get_best_context(self, query: str, max_articles: int = 5, include_books: bool = False) -> str:
        # For human-readable context output, debugging
        results = await self.search(query, max_results=max_articles, include_books=include_books)
        articles: list[Article] = results["articles"][:max_articles]
        books: list[BookSection] = results["books"]

        context_parts = []

        for i, article in enumerate(articles, 1):
            section = f"[Article {i}] {article.title}"
            if article.authors:
                section += f"\nAuthors: {', '.join(article.authors[:3])}"
            section += f"\nJournal: {article.journal} ({article.year})"
            section += f"\nStudy Type: {article.study_type}"
            section += f"\nCitations: {article.citation_count}"
            section += f"\nQuality Score: {article.quality_score}"
            section += f"\nSource: {article.source}"
            section += f"\nFull Text Available: {article.full_text_available}"
            if article.doi:
                section += f"\nDOI: {article.doi}"
            if article.pdf_url:
                section += f"\nPDF Link: {article.pdf_url}"
    
            if article.full_text:
                content = article.full_text[:200] + "..." if len(article.full_text) > 200 else article.full_text
                section += f"\n\nFull Text:\n{content}"
            elif article.abstract:
                section += f"\n\nAbstract:\n{article.abstract[:200]}"

            context_parts.append(section)

        for book in books:
            section = f"[Textbook] {book.title or 'Medical Reference'}"
            section += f"\nSource: {book.source or 'NCBI Bookshelf'}"
            text = book.text
            if text:
                section += f"\n\n{text[:2000]}..."
            context_parts.append(section)
            print(book)
        return "\n\n" + ("─" * 60 + "\n\n").join(context_parts)


    async def get_json_content(
        self,
        query: str,
        max_articles: int = 5,
        include_books: bool = False,
    ) -> dict:
        results = await self.search(query, max_results=max_articles, include_books=include_books)
        articles = [asdict(a) for a in results["articles"][:max_articles]]
        books = [asdict(b) for b in results["books"]]
        return {"query": query, "articles": articles, "books": books}

def clean_text_for_llm(text):
    if not isinstance(text, str):
        if text is None:
            return ""
        text = str(text)

    # Normalize Unicode
    text = unicodedata.normalize('NFKC', text)
    
    # Remove control characters except newlines/tabs
    text = ''.join(c for c in text if unicodedata.category(c)[0] != 'C' or c in '\n\r\t')
    
    # Remove zero-width characters
    text = re.sub(r'[\u200b-\u200d\ufeff]', '', text)
    
    # Normalize horizontal whitespace (spaces, tabs) to a single space
    text = re.sub(r'[ \t]+', ' ', text)
    
    # Normalize multiple newlines to a maximum of two (paragraph break)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()


def normalize_identifier(value):
    if value is None:
        return None

    normalized = clean_text_for_llm(value)
    if not normalized:
        return None

    return normalized.lower()


def build_article_identity(article: dict) -> tuple[str, str] | None:
    for field in ("doi", "pubmed_id", "pmc_id", "openalex_id"):
        identifier = normalize_identifier(article.get(field))
        if identifier:
            return (field, identifier)

    title = normalize_identifier(article.get("title"))
    year = article.get("year") or ""
    journal = normalize_identifier(article.get("journal")) or ""
    return ("title", f"{title}|{year}|{journal}")

def normalize_articles(articles: list[dict]) -> list[dict]:
    for article in articles:
        full_text = clean_text_for_llm(article.get("full_text", ""))
        if len(full_text) < 100:
            article["full_text"] = "FULL TEXT NOT AVAILABLE"
        else:
            article["full_text"] = full_text
        for key in ["title", "abstract", "full_text"]:
            article[key] = clean_text_for_llm(article.get(key, ""))
    return articles

def deduplicate_articles(articles: list[dict]) -> list[dict]:
    seen = set()
    unique_articles = []
    for article in articles:
        identifier = build_article_identity(article)
        if identifier is None:
            unique_articles.append(article)
            continue

        if identifier in seen:
            continue

        seen.add(identifier)
        unique_articles.append(article)
    return unique_articles
        
async def run_pipeline(query: str, max_articles: int = 5, include_books: bool = False) -> dict:
    """
    Run the medical knowledge pipeline with a given query.
    
    This function orchestrates the entire process of retrieving and processing medical literature based on the input query. It returns a structured dictionary containing the relevant articles and book sections.
    Sources include PubMed, PMC, OpenAlex, and NCBI Bookshelf. The output is normalized and cleaned.
    
    Args:
        query (str): The medical query to search for.
        max_articles (int): The maximum number of articles to retrieve and process.
        include_books (bool): Whether to include book sections from NCBI Bookshelf in the results.
    
    Returns:
        dict: A dictionary containing the query, a list of articles, and a list of book sections.
    """

    pipeline = MedicalKnowledgePipeline()
    context = await pipeline.get_json_content(
        query,
        max_articles=max_articles,
        include_books=include_books,
    )
    articles = context["articles"]
    books = context["books"]

    articles = deduplicate_articles(articles)
    articles = [a for a in articles if a["full_text_available"] or a["abstract"]]
    articles = normalize_articles(articles)

    return {"articles": articles, "books": books}

if __name__ == "__main__":
    import asyncio
    context = asyncio.run(run_pipeline("inguinal hernia repair"))

    print(json.dumps(context, indent=2, ensure_ascii=False))
