import asyncio
import json
from dataclasses import asdict

from .pdf_utils import PDFClient
from .books import NCBIBooksClient
from .models import Article, Book
from .openalex import OpenAlexClient
from .pmc import PMCClient
from .pubmed import PubMedClient
from .ranking import QualityRanker


class MedicalKnowledgePipeline:
    def __init__(self):
        self.pubmed = PubMedClient()
        self.pmc = PMCClient()
        self.openalex = OpenAlexClient()
        self.ncbi_books = NCBIBooksClient()
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

        books = []
        if include_books:
            books = self.ncbi_books.search_books(query, max_results=3)

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
        results = self.search(query, max_results=max_articles, include_books=include_books)
        articles: list[Article] = results["articles"][:max_articles]
        books: list[Book] = results["books"]

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
            section += f"\nText Source: {book.text_source}"
            section += f"\nPDF URL Found: {book.pdf_url_found}"
            section += f"\nPDF Text Extracted: {book.pdf_text_extracted}"
            text = book.text
            if text:
                section += f"\n\n{text[:2000]}..."
            context_parts.append(section)
            print(book)
        return "\n\n" + ("─" * 60 + "\n\n").join(context_parts)

    def get_json_content(self, query: str, max_articles: int = 5, include_books: bool = False) -> dict:
        results = self.search(query, max_results=max_articles, include_books=include_books)
        articles = [asdict(a) for a in results["articles"][:max_articles]]
        books = [asdict(b) for b in results["books"]]
        return {"query": query, "articles": articles, "books": books}
    
if __name__ == "__main__":
    pipeline = MedicalKnowledgePipeline()
    context = pipeline.get_json_content("inguinal hernia", max_articles=10)
    for article in context["articles"]:
        article["full_text"] = article["full_text"][:300] + "..." if article["full_text"] else None
    print(json.dumps(context, indent=2))