import asyncio
import json
from dataclasses import asdict
import re
import unicodedata
import uuid

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

    def search(self, query: str, max_results: int = 10, include_books: bool = True) -> dict:
        print(f"\n{'='*60}")
        print(f"MEDICAL PIPELINE — Query: '{query}'")
        print(f"{'='*60}")

        pubmed_ids = self.pubmed.search(query, max_results=max_results)
        articles = self.pubmed.fetch_abstracts(pubmed_ids)

        for article in articles:
            article.source = "PubMed Abstract"

        articles = self.pmc.enrich_articles_with_fulltext(articles)
        articles = self.openalex.enrich_articles(articles)
        for article in articles:
            if not article.full_text_available and article.pdf_url:
                article.full_text = asyncio.run(self.pdf_client.get_pdf_content(article.pdf_url))
                article.full_text_available = bool(article.full_text)

        openalex_articles = self.openalex.search_directly(query, max_results=int(max_results*0.6))
        articles.extend(openalex_articles)

        books = []
        if include_books:
            books = self.bookshelf.get_book_contents(query, num_results=3)

        articles = self.ranker.rank(articles)

        full_text_count = sum(1 for a in articles if a.full_text_available)
        pdf_count = sum(1 for a in articles if a.pdf_url and not a.full_text_available)
        abstract_count = len(articles) - full_text_count - pdf_count

        print(f"\n{'='*60}")
        print("RESULTS SUMMARY")
        print(f"  Total articles : {len(articles)}")
        print(f"  Full text (PMC): {full_text_count}")
        print(f"  PDF links (OA) : {pdf_count}")
        print(f"  Abstract only  : {abstract_count}")
        print(f"  Book sections  : {len(books)}")
        print(f"{'='*60}\n")

        return {
            "query": query,
            "articles": articles,
            "books": books,
        }

    def get_best_context(self, query: str, max_articles: int = 5, include_books: bool = False) -> str:
        # For human-readable context output, debugging
        results = self.search(query, max_results=max_articles, include_books=include_books)
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


    def get_json_content(
        self,
        query: str,
        max_articles: int = 5,
        include_books: bool = False,
    ) -> dict:
        results = self.search(query, max_results=max_articles, include_books=include_books)
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

def normalize_articles(articles:dict) -> str:
    for article in articles:
        if len(article.get("full_text", "")) < 100:
            article["full_text"] = "FULL TEXT NOT AVAILABLE"
        for key in ["title", "abstract", "full_text"]:
            article[key] = clean_text_for_llm(article.get(key, ""))
    return articles

def deduplicate_articles(articles: list[dict]) -> list[dict]:
    seen = set()
    unique_articles = []
    for article in articles:
        identifier = (article.get("title", uuid.uuid4().hex).lower(), article.get("doi", uuid.uuid4().hex).lower())
        if identifier not in seen:
            seen.add(identifier)
            unique_articles.append(article)
    return unique_articles
        
def run_pipeline(query: str, max_articles: int = 5, include_books: bool = False) -> dict:
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
    context = pipeline.get_json_content(
        query,
        max_articles=max_articles,
        include_books=include_books,
    )
    articles = context["articles"]
    books = context["books"]

    articles = deduplicate_articles(articles)
    articles = [a for a in articles if a["full_text_available"] or a["abstract"]]
    articles = normalize_articles(articles)
    
    fields = [
        "title",
        "abstract",
        "full_text",
        "year",
        "mesh_terms",
        "study_type",
        # "pdf_url",
    ]
    
    filtered_context = []
    for article in articles:
        filtered_article = {field: article.get(field) for field in fields if field in article}
        filtered_context.append(filtered_article)

    return {"articles": filtered_context, "books": books}

if __name__ == "__main__":
    context = run_pipeline("inguinal hernia repair")

    print(json.dumps(context, indent=2, ensure_ascii=False))