import re
from db.models import Article, BookSection, WebSearchResult


def sanitize_markdown(content: str) -> str:
    """Remove custom XML-style wrappers that Textual markdown won't display."""
    return re.sub(r"</?source>", "", content or "")
    
def build_missing_source_markdown(citation_number: str, citation: dict | None) -> str:
    title = (citation or {}).get("title") or f"Source {citation_number}"
    lines = [f"# [{citation_number}] {title}", "", "_No stored source content is available for this citation._"]

    url = (citation or {}).get("url")
    doi = (citation or {}).get("doi")
    if url:
        lines.extend(["", f"[Open source]({url})"])
    elif doi:
        lines.extend(["", f"[Open DOI](https://doi.org/{doi})"])

    return "\n".join(lines)


def format_article_markdown(citation_number: str, article: Article) -> str:
    title = article.title or f"Source {citation_number}"
    lines = [f"# [{citation_number}] {title}", "", "- Type: Article"]

    if article.journal or article.year:
        journal_line = article.journal or "Unknown journal"
        if article.year:
            journal_line = f"{journal_line} ({article.year})"
        lines.append(f"- Journal: {journal_line}")
    if article.study_type:
        lines.append(f"- Study type: {article.study_type}")
    if article.source:
        lines.append(f"- Database: {article.source}")
    if article.doi:
        lines.append(f"- DOI: [{article.doi}](https://doi.org/{article.doi})")
    if article.pdf_url:
        lines.append(f"- PDF: [Open PDF]({article.pdf_url})")
    if article.authors:
        lines.append(f"- Authors: {', '.join(article.authors)}")

    if article.abstract:
        lines.extend(["", "## Abstract", "", sanitize_markdown(article.abstract)])
    if article.full_text:
        lines.extend(["", "## Full Text", "", sanitize_markdown(article.full_text)])
    elif not article.abstract:
        lines.extend(["", "_No stored article text is available for this source._"])

    return "\n".join(lines)


def format_book_section_markdown(citation_number: str, section: BookSection) -> str:
    title = section.title or f"Source {citation_number}"
    lines = [f"# [{citation_number}] {title}", "", "- Type: Book Section"]

    if section.source:
        lines.append(f"- Source: {section.source}")
    if section.url:
        lines.append(f"- URL: [Open source]({section.url})")

    if section.text:
        lines.extend(["", "## Content", "", sanitize_markdown(section.text)])
    else:
        lines.extend(["", "_No stored section text is available for this source._"])

    return "\n".join(lines)


def format_web_result_markdown(citation_number: str, result: WebSearchResult) -> str:
    title = result.title or f"Source {citation_number}"
    lines = [f"# [{citation_number}] {title}", "", "- Type: Web Result"]

    if result.url:
        lines.append(f"- URL: [Open source]({result.url})")
    if result.query:
        lines.append(f"- Search query: `{result.query}`")

    if result.highlights:
        lines.extend(["", "## Highlights", "", sanitize_markdown(result.highlights)])
    if result.full_content:
        lines.extend(["", "## Full Content", "", sanitize_markdown(result.full_content)])
    elif not result.highlights:
        lines.extend(["", "_No stored web content is available for this source._"])

    return "\n".join(lines)


def build_source_documents(
    sources: dict[str, list[tuple[Article | BookSection | WebSearchResult, int | None]]],
    citations: dict[str, dict],
) -> dict[str, str]:
    documents: dict[str, str] = {}

    for source_type, source_rows in sources.items():
        for source, citation_num in source_rows:
            if citation_num is None:
                continue

            citation_key = str(citation_num)
            if source_type == "articles":
                documents[citation_key] = format_article_markdown(citation_key, source)
            elif source_type == "book_sections":
                documents[citation_key] = format_book_section_markdown(citation_key, source)
            else:
                documents[citation_key] = format_web_result_markdown(citation_key, source)

    for citation_key, citation in citations.items():
        documents.setdefault(
            citation_key,
            build_missing_source_markdown(citation_key, citation),
        )

    return documents