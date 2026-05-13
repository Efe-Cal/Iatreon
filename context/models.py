from dataclasses import dataclass, field


@dataclass
class Article:
    pubmed_id: str = ""
    pmc_id: str = ""
    doi: str = ""
    openalex_id: str = ""

    title: str = ""
    abstract: str = ""
    full_text: str = ""
    pdf_url: str = ""

    authors: list = field(default_factory=list)
    journal: str = ""
    year: int = 0
    study_type: str = ""
    keywords: list = field(default_factory=list)
    mesh_terms: list = field(default_factory=list)

    citation_count: int = 0
    quality_score: float = 0.0
    full_text_available: bool = False
    source: str = ""


@dataclass
class Book:
    accession_id: str = ""
    title: str = ""
    source: str = ""
    
    text: str = ""
    url: str = ""
    full_text_available: bool = False