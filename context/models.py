from dataclasses import dataclass, field


@dataclass
class Article:
    pubmed_id: str | None = None
    pmc_id: str | None = None
    doi: str | None = None
    openalex_id: str | None = None
    title: str = ""
    abstract: str | None = ""
    full_text: str | None = ""
    pdf_url: str | None = ""
    authors: list[str] = field(default_factory=list)
    journal: str | None = ""
    year: int | None = 0
    study_type: str | None = ""
    keywords: list[str] = field(default_factory=list)
    mesh_terms: list[str] = field(default_factory=list)
    citation_count: int | None = 0
    quality_score: float | None = 0.0
    full_text_available: bool = False
    source: str | None = ""


@dataclass
class BookSection:
    accession_id: str = ""
    title: str = ""
    source: str = ""
    text: str = ""
    url: str | None = ""
    full_text_available: bool = True
