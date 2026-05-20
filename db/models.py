from sqlalchemy import String, Text, Integer, Float, Boolean, ForeignKey, DateTime, JSON, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
from typing import Optional
import uuid
from .db import Base

class User(Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String, unique=True)
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default_factory=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default_factory=datetime.utcnow)

class UserProfile(Base):
    __tablename__ = "user_profile"
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    demographics: Mapped[Optional[dict]] = mapped_column(JSON, default=None)
    pmh: Mapped[Optional[list]] = mapped_column(JSON, default_factory=list)
    medications: Mapped[Optional[list]] = mapped_column(JSON, default_factory=list)
    allergies: Mapped[Optional[list]] = mapped_column(JSON, default_factory=list)
    family_history: Mapped[Optional[list]] = mapped_column(JSON, default_factory=list)
    social: Mapped[Optional[dict]] = mapped_column(JSON, default=None)
    medical_summary: Mapped[Optional[str]] = mapped_column(Text, default=None)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default_factory=datetime.utcnow, onupdate=datetime.utcnow)

class IntakeSession(Base):
    __tablename__ = "intake_sessions"
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default_factory=uuid.uuid4)
    chief_complaint: Mapped[Optional[str]] = mapped_column(Text, default=None)
    symptoms: Mapped[Optional[list]] = mapped_column(JSON, default_factory=list)
    red_flags: Mapped[Optional[list]] = mapped_column(JSON, default_factory=list)
    medical_summary: Mapped[Optional[str]] = mapped_column(Text, default=None)
    raw_transcript: Mapped[Optional[list]] = mapped_column(JSON, default_factory=list)
    status: Mapped[str] = mapped_column(String, default="in_progress")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default_factory=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)

class ResearchSession(Base):
    __tablename__ = "research_sessions"
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default_factory=uuid.uuid4)
    intake_session_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("intake_sessions.id"), default=None)
    articles: Mapped[list["SessionArticle"]] = relationship(back_populates="session", default_factory=list, cascade="all, delete-orphan")
    books: Mapped[list["SessionBookSection"]] = relationship(back_populates="session", default_factory=list, cascade="all, delete-orphan")
    web_search_results: Mapped[list["SessionWebSearchResult"]] = relationship(back_populates="session", default_factory=list, cascade="all, delete-orphan")
    research_report: Mapped[Optional[str]] = mapped_column(Text, default=None)
    citations: Mapped[Optional[dict[int, dict]]] = mapped_column(JSON, default_factory=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default_factory=datetime.utcnow)

class WebSearchResult(Base):
    __tablename__ = "web_search_results"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default_factory=uuid.uuid4)
    query: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String, default="")
    title: Mapped[Optional[str]] = mapped_column(String, default="")
    highlights: Mapped[Optional[str]] = mapped_column(Text, default="")
    full_content: Mapped[Optional[str]] = mapped_column(Text, default="")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default_factory=datetime.utcnow)


class Article(Base):
    __tablename__ = "articles"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default_factory=uuid.uuid4)
    pubmed_id: Mapped[Optional[str]] = mapped_column(String, unique=True, default=None)
    pmc_id: Mapped[Optional[str]] = mapped_column(String, unique=True, default=None)
    doi: Mapped[Optional[str]] = mapped_column(String, unique=True, default=None)
    openalex_id: Mapped[Optional[str]] = mapped_column(String, unique=True, default=None)
    title: Mapped[str] = mapped_column(Text, default="")
    abstract: Mapped[Optional[str]] = mapped_column(Text, default="")
    full_text: Mapped[Optional[str]] = mapped_column(Text, default="")
    pdf_url: Mapped[Optional[str]] = mapped_column(String, default="")
    authors: Mapped[Optional[list]] = mapped_column(JSON, default_factory=list)
    journal: Mapped[Optional[str]] = mapped_column(String, default="")
    year: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    study_type: Mapped[Optional[str]] = mapped_column(String, default="")
    keywords: Mapped[Optional[list]] = mapped_column(JSON, default_factory=list)
    mesh_terms: Mapped[Optional[list]] = mapped_column(JSON, default_factory=list)
    citation_count: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    quality_score: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    full_text_available: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[Optional[str]] = mapped_column(String, default="")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default_factory=datetime.utcnow)

class BookSection(Base):
    __tablename__ = "book_sections"
    accession_id: Mapped[str] = mapped_column(String, unique=True)
    title: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String)
    text: Mapped[Optional[str]] = mapped_column(Text)
    url: Mapped[Optional[str]] = mapped_column(String)
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default_factory=uuid.uuid4)
    full_text_available: Mapped[bool] = mapped_column(Boolean, default=False)


class SessionArticle(Base):
    __tablename__ = "session_articles"
    query: Mapped[str] = mapped_column(Text)
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("research_sessions.id"))
    article_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("articles.id"))
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default_factory=uuid.uuid4)
    session: Mapped["ResearchSession"] = relationship(back_populates="articles", init=False, repr=False)
    article: Mapped["Article"] = relationship(init=False, repr=False)
    quality_score: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    citation_num: Mapped[Optional[int]] = mapped_column(Integer, default=0)

class SessionBookSection(Base):
    __tablename__ = "session_book_sections"
    query: Mapped[str] = mapped_column(Text)
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("research_sessions.id"))
    book_section_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("book_sections.id"))
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default_factory=uuid.uuid4)
    session: Mapped["ResearchSession"] = relationship(back_populates="books", init=False, repr=False)
    book_section: Mapped["BookSection"] = relationship(init=False, repr=False)
    citation_num: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    
class SessionWebSearchResult(Base):
    __tablename__ = "session_web_search_results"
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("research_sessions.id"))
    web_search_result_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("web_search_results.id"))
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default_factory=uuid.uuid4)
    session: Mapped["ResearchSession"] = relationship(back_populates="web_search_results", init=False, repr=False)
    web_search_result: Mapped["WebSearchResult"] = relationship(init=False, repr=False)
    citation_num: Mapped[Optional[int]] = mapped_column(Integer, default=0)