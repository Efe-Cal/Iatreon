from calendar import c

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta
import uuid
from .models import (
    IntakeSession,
    Article,
    ResearchSession,
    SessionArticle,
    BookSection,
    SessionBookSection,
    User,
    UserProfile,
    WebSearchResult,
    SessionWebSearchResult,
)
from .schemas import BookSectionData, IntakeProfile, ArticleData, UserProfileData


def _normalize_unique_identifier(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.strip()
    if not normalized:
        return None

    return normalized.lower()

class IntakeRepo:
    def __init__(self, user_id: str):
        self.user_id = uuid.UUID(user_id)

    @staticmethod
    def _serialize_transcript(transcript: list) -> list[dict]:
        serialized_transcript = []
        for message in transcript:
            if hasattr(message, "model_dump"):
                serialized_transcript.append(message.model_dump())
            elif isinstance(message, dict):
                serialized_transcript.append(message)
            else:
                serialized_transcript.append({"type": message.__class__.__name__, "content": str(message)})
        return serialized_transcript

    async def create_session(self, db: AsyncSession) -> IntakeSession:
        session = IntakeSession(user_id=self.user_id, status="in_progress", raw_transcript=[])
        db.add(session)
        await db.flush()
        return session

    async def get_or_create_session(self, db: AsyncSession, session_id: uuid.UUID) -> IntakeSession:
        session = await db.get(IntakeSession, session_id)
        if session:
            if session.user_id != self.user_id:
                raise ValueError("Unauthorized: User ID mismatch")
            return session
        
        session = IntakeSession(id=session_id, user_id=self.user_id, status="in_progress", raw_transcript=[])
        db.add(session)
        await db.flush()
        return session

    async def update_session(self, db: AsyncSession, session_id: uuid.UUID, profile: IntakeProfile, transcript: list):
        session = await db.get(IntakeSession, session_id)
        if session.user_id != self.user_id:
            return "Error: Unauthorized"
        session.chief_complaint = profile.chief_complaint
        session.symptoms = [s.model_dump() for s in profile.symptoms]
        session.red_flags = profile.red_flags
        session.medical_summary = profile.medical_summary
        session.raw_transcript = self._serialize_transcript(transcript)
        await db.flush()
        return "OK"

    async def complete_session(self, db: AsyncSession, session_id: uuid.UUID):
        session = await db.get(IntakeSession, session_id)
        if session.user_id != self.user_id:
            return "Error: Unauthorized"
        session.status = "complete"
        session.completed_at = datetime.utcnow()
        await db.flush()
        return "OK"

    async def get_session(self, db: AsyncSession, session_id: uuid.UUID) -> IntakeSession | None:
        if isinstance(session_id, str):
            session_id = uuid.UUID(session_id)

        session = await db.get(IntakeSession, session_id)
        if session and session.user_id == self.user_id:
            return session
        return None

class ResearchRepo:
    def __init__(self, user_id: str):
        self.user_id = uuid.UUID(user_id)

    async def create_research_session(self, db: AsyncSession, intake_session_id: uuid.UUID) -> ResearchSession:
        session = ResearchSession(user_id=self.user_id, intake_session_id=intake_session_id)
        db.add(session)
        await db.flush()
        return session

    async def update_research_session(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
        research_report: str | None = None,
        citations: dict[int, dict] | None = None,
    ) -> ResearchSession | None:
        session = await db.get(ResearchSession, session_id)
        if session is None or session.user_id != self.user_id:
            return None

        if research_report is not None:
            session.research_report = research_report
        if citations is not None:
            session.citations = citations

        await db.flush()
        return session

    async def get_research_session(self, db: AsyncSession, session_id: uuid.UUID) -> ResearchSession | None:
        if isinstance(session_id, str):
            session_id = uuid.UUID(session_id)
        
        session = await db.get(ResearchSession, session_id)
        if session and session.user_id == self.user_id:
            return session
        return None

    async def get_research_session_by_intake_id(self, db: AsyncSession, intake_session_id: uuid.UUID) -> ResearchSession | None:
        if isinstance(intake_session_id, str):
            intake_session_id = uuid.UUID(intake_session_id)

        stmt = select(ResearchSession).where(
            ResearchSession.intake_session_id == intake_session_id,
            ResearchSession.user_id == self.user_id,
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    async def link_article(self, db: AsyncSession, session_id: uuid.UUID, article_id: uuid.UUID, query: str, quality_score: float | None = None) -> SessionArticle:
        existing_stmt = select(SessionArticle).where(
            SessionArticle.session_id == session_id,
            SessionArticle.article_id == article_id,
        )
        existing = (await db.execute(existing_stmt)).scalar_one_or_none()

        if existing is not None:
            existing.query = query
            existing.quality_score = quality_score
            await db.flush()
            return existing

        link = SessionArticle(
            session_id=session_id,
            article_id=article_id,
            query=query,
            quality_score=quality_score,
        )
        db.add(link)
        await db.flush()
        return link

    async def link_book_section(self, db: AsyncSession, session_id: uuid.UUID, book_section_id: uuid.UUID, query: str) -> SessionBookSection:
        existing_stmt = select(SessionBookSection).where(
            SessionBookSection.session_id == session_id,
            SessionBookSection.book_section_id == book_section_id,
        )
        existing = (await db.execute(existing_stmt)).scalar_one_or_none()

        if existing is not None:
            existing.query = query
            await db.flush()
            return existing

        link = SessionBookSection(
            session_id=session_id,
            book_section_id=book_section_id,
            query=query,
        )
        db.add(link)
        await db.flush()
        return link

    async def link_web_search_result(self, db: AsyncSession, session_id: uuid.UUID, web_search_result_id: uuid.UUID) -> SessionWebSearchResult:
        existing_stmt = select(SessionWebSearchResult).where(
            SessionWebSearchResult.session_id == session_id,
            SessionWebSearchResult.web_search_result_id == web_search_result_id,
        )
        existing = (await db.execute(existing_stmt)).scalar_one_or_none()

        if existing is not None:
            return existing

        link = SessionWebSearchResult(
            session_id=session_id,
            web_search_result_id=web_search_result_id,
        )
        db.add(link)
        await db.flush()
        return link

    async def get_session_articles(self, db: AsyncSession, session_id: uuid.UUID, limit: int = 8) -> list[Article]:
        stmt = (
            select(Article)
            .join(SessionArticle, SessionArticle.article_id == Article.id)
            .where(SessionArticle.session_id == session_id)
            .order_by(SessionArticle.quality_score.desc().nullslast())
            .limit(limit)
        )
        return list((await db.execute(stmt)).scalars())

    async def get_session_book_sections(self, db: AsyncSession, session_id: uuid.UUID, limit: int = 8) -> list[BookSection]:
        stmt = (
            select(BookSection)
            .join(SessionBookSection, SessionBookSection.book_section_id == BookSection.id)
            .where(SessionBookSection.session_id == session_id)
            .limit(limit)
        )
        return list((await db.execute(stmt)).scalars())

    async def get_session_web_search_results(self, db: AsyncSession, session_id: uuid.UUID, limit: int = 8) -> list[WebSearchResult]:
        stmt = (
            select(WebSearchResult)
            .join(SessionWebSearchResult, SessionWebSearchResult.web_search_result_id == WebSearchResult.id)
            .where(SessionWebSearchResult.session_id == session_id)
            .order_by(WebSearchResult.fetched_at.desc())
            .limit(limit)
        )
        return list((await db.execute(stmt)).scalars())
    
    async def get_all_session_sources(self, db: AsyncSession, session_id: uuid.UUID) -> dict[str, list[tuple[Article | BookSection | WebSearchResult, int | None]]]:
        stmt = (
            select(Article, SessionArticle)
            .join(SessionArticle, SessionArticle.article_id == Article.id)
            .where(SessionArticle.session_id == session_id)
        )
        articles = (await db.execute(stmt)).all()
        
        stmt = (
            select(BookSection, SessionBookSection)
            .join(SessionBookSection, SessionBookSection.book_section_id == BookSection.id)
            .where(SessionBookSection.session_id == session_id)
        )
        book_sections = (await db.execute(stmt)).all()
        
        stmt = (
            select(WebSearchResult, SessionWebSearchResult)
            .join(SessionWebSearchResult, SessionWebSearchResult.web_search_result_id == WebSearchResult.id)
            .where(SessionWebSearchResult.session_id == session_id)
        )
        web_search_results = (await db.execute(stmt)).all()
        
        sources = {
            "articles": [(article, session_article.citation_num )for article, session_article in articles],
            "book_sections": [(book_section, session_book.citation_num) for book_section, session_book in book_sections],
            "web_search_results": [(web_search_result, session_web_search.citation_num) for web_search_result, session_web_search in web_search_results],
        }
        return sources

class ArticleRepo:
    def __init__(self):
        pass

    async def upsert(self, db: AsyncSession, data: ArticleData) -> Article:
        """Insert or update an article row and return it."""
        pubmed_id = _normalize_unique_identifier(data.pubmed_id)
        pmc_id = _normalize_unique_identifier(data.pmc_id)
        doi = _normalize_unique_identifier(data.doi)
        openalex_id = _normalize_unique_identifier(data.openalex_id)

        payload = {
            "pubmed_id": pubmed_id,
            "pmc_id": pmc_id,
            "doi": doi,
            "openalex_id": openalex_id,
            "title": data.title,
            "abstract": data.abstract,
            "full_text": data.full_text,
            "pdf_url": data.pdf_url,
            "authors": data.authors,
            "journal": data.journal,
            "year": data.year,
            "study_type": data.study_type,
            "keywords": data.keywords,
            "mesh_terms": data.mesh_terms,
            "citation_count": data.citation_count,
            "quality_score": data.quality_score,
            "full_text_available": data.full_text_available,
            "source": data.source,
            "fetched_at": datetime.utcnow(),
        }

        identity_filters = [
            Article.pubmed_id == pubmed_id if pubmed_id else None,
            Article.pmc_id == pmc_id if pmc_id else None,
            Article.doi == doi if doi else None,
            Article.openalex_id == openalex_id if openalex_id else None,
        ]
        identity_filters = [clause for clause in identity_filters if clause is not None]

        existing = None
        if identity_filters:
            existing_stmt = select(Article).where(or_(*identity_filters))
            existing = (await db.execute(existing_stmt)).scalar_one_or_none()

        if existing is not None:
            for field, value in payload.items():
                setattr(existing, field, value)
            await db.flush()
            return existing

        article = Article(**payload)
        await db.add(article)
        await db.flush()
        return article

    async def get_cached(
        self,
        db: AsyncSession,
        pubmed_id: str | None = None,
        pmc_id: str | None = None,
        doi: str | None = None,
        openalex_id: str | None = None,
        max_age_days: int = 30,
    ) -> Article | None:
        cutoff = datetime.utcnow() - timedelta(days=max_age_days)
        pubmed_id = _normalize_unique_identifier(pubmed_id)
        pmc_id = _normalize_unique_identifier(pmc_id)
        doi = _normalize_unique_identifier(doi)
        openalex_id = _normalize_unique_identifier(openalex_id)
        identity_filters = [
            Article.pubmed_id == pubmed_id if pubmed_id else None,
            Article.pmc_id == pmc_id if pmc_id else None,
            Article.doi == doi if doi else None,
            Article.openalex_id == openalex_id if openalex_id else None,
        ]
        identity_filters = [clause for clause in identity_filters if clause is not None]
        if not identity_filters:
            return None

        stmt = select(Article).where(or_(*identity_filters), Article.fetched_at > cutoff)
        return (await db.execute(stmt)).scalar_one_or_none()
    
    async def link_to_session(self, db: AsyncSession, session_id: uuid.UUID, article_id: uuid.UUID, query: str, quality_score: float, citation_num: int = 0) -> SessionArticle:
        existing_stmt = select(SessionArticle).where(
            SessionArticle.session_id == session_id,
            SessionArticle.article_id == article_id,
        )
        existing = (await db.execute(existing_stmt)).scalar_one_or_none()

        if existing is not None:
            existing.query = query
            existing.quality_score = quality_score
            existing.citation_num = citation_num
            await db.flush()
            return existing

        link = SessionArticle(
            session_id=session_id,
            article_id=article_id,
            query=query,
            quality_score=quality_score,
            citation_num=citation_num,
        )
        await db.add(link)
        await db.flush()
        return link

    async def get_session_articles(self, db: AsyncSession, session_id: uuid.UUID, limit: int = 8) -> list[Article]:
        stmt = (
            select(Article)
            .join(SessionArticle, SessionArticle.article_id == Article.id)
            .where(SessionArticle.session_id == session_id)
            .order_by(SessionArticle.quality_score.desc().nullslast())
            .limit(limit)
        )
        return list((await db.execute(stmt)).scalars())
    
    async def get_article_by_id(self, db: AsyncSession, article_id: uuid.UUID) -> Article | None:
        return await db.get(Article, article_id)

class BookSectionRepo:
    def __init__(self):
        pass
    
    async def upsert(self, db: AsyncSession, data: BookSectionData) -> BookSection:
        existing_stmt = select(BookSection).where(BookSection.accession_id == data.accession_id)
        existing = (await db.execute(existing_stmt)).scalar_one_or_none()

        if existing is not None:
            existing.title = data.title
            existing.source = data.source
            existing.text = data.text
            existing.url = data.url
            existing.full_text_available = data.full_text_available
            await db.flush()
            return existing

        section = BookSection(
            accession_id=data.accession_id,
            title=data.title,
            source=data.source,
            text=data.text,
            url=data.url,
            full_text_available=data.full_text_available,
        )
        await db.add(section)
        await db.flush()
        return section

    async def get_by_accession_id(self, db: AsyncSession, accession_id: str) -> BookSection | None:
        stmt = select(BookSection).where(BookSection.accession_id == accession_id)
        return (await db.execute(stmt)).scalar_one_or_none()
    
    async def link_to_session(self, db: AsyncSession, session_id: uuid.UUID, book_section_id: uuid.UUID, query: str, citation_num: int = 0) -> SessionBookSection:
        existing_stmt = select(SessionBookSection).where(
            SessionBookSection.session_id == session_id,
            SessionBookSection.book_section_id == book_section_id,
        )
        existing = (await db.execute(existing_stmt)).scalar_one_or_none()

        if existing is not None:
            existing.query = query
            existing.citation_num = citation_num
            await db.flush()
            return existing

        link = SessionBookSection(
            session_id=session_id,
            book_section_id=book_section_id,
            query=query,
            citation_num=citation_num
        )
        await db.add(link)
        await db.flush()
        return link
        
    async def get_session_book_sections(self, db: AsyncSession, session_id: uuid.UUID, limit: int = 8) -> list[BookSection]:
        stmt = (
            select(BookSection)
            .join(SessionBookSection, SessionBookSection.book_section_id == BookSection.id)
            .where(SessionBookSection.session_id == session_id)
            .limit(limit)
        )
        return list((await db.execute(stmt)).scalars())
    
    async def get_book_section_by_id(self, db: AsyncSession, book_section_id: uuid.UUID) -> BookSection | None:
        return await db.get(BookSection, book_section_id)

class WebSearchResultRepo:
    def __init__(self):
        pass

    async def upsert(self, db: AsyncSession, query: str, url: str, title: str | None, highlights: str | None, full_content: str | None) -> WebSearchResult:
        existing_stmt = select(WebSearchResult).where(WebSearchResult.query == query, WebSearchResult.url == url)
        existing = (await db.execute(existing_stmt)).scalar_one_or_none()

        if existing is not None:
            existing.title = title
            existing.highlights = highlights
            existing.full_content = full_content
            existing.fetched_at = datetime.utcnow()
            await db.flush()
            return existing

        result = WebSearchResult(
            query=query,
            url=url,
            title=title,
            highlights=highlights,
            full_content=full_content,
        )
        await db.add(result)
        await db.flush()
        return result

    async def link_to_session(self, db: AsyncSession, session_id: uuid.UUID, web_search_result_id: uuid.UUID, citation_num: int = 0) -> SessionWebSearchResult:
        existing_stmt = select(SessionWebSearchResult).where(
            SessionWebSearchResult.session_id == session_id,
            SessionWebSearchResult.web_search_result_id == web_search_result_id,
        )
        existing = (await db.execute(existing_stmt)).scalar_one_or_none()

        if existing is not None:
            existing.citation_num = citation_num
            await db.flush()
            return existing

        link = SessionWebSearchResult(
            session_id=session_id,
            web_search_result_id=web_search_result_id,
            citation_num=citation_num,
        )
        await db.add(link)
        await db.flush()
        return link

    async def get_session_web_search_results(self, db: AsyncSession, session_id: uuid.UUID, limit: int = 8) -> list[WebSearchResult]:
        stmt = (
            select(WebSearchResult)
            .join(SessionWebSearchResult, SessionWebSearchResult.web_search_result_id == WebSearchResult.id)
            .where(SessionWebSearchResult.session_id == session_id)
            .order_by(WebSearchResult.fetched_at.desc())
            .limit(limit)
        )
        return list((await db.execute(stmt)).scalars())

    async def get_web_search_result_by_id(self, db: AsyncSession, web_search_result_id: uuid.UUID) -> WebSearchResult | None:
        return await db.get(WebSearchResult, web_search_result_id)


class UserRepo:
    def __init__(self):
        pass
    
    async def create_user(self, db: AsyncSession, ssh_key: str) -> User:
        user = User(ssh_key=ssh_key)
        await db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    async def get_user_id_by_ssh_key(self, db: AsyncSession, ssh_key: str) -> uuid.UUID | None:
        stmt = select(User.id).where(User.ssh_key == ssh_key)
        return (await db.execute(stmt)).scalar_one_or_none()
    
    async def get_user_profile(self, db: AsyncSession, user_id: uuid.UUID) -> dict:
        stmt = select(UserProfile).where(UserProfile.user_id == user_id)
        user_profile = (await db.execute(stmt)).scalar_one_or_none()
        if user_profile is None:
            return {}
        return UserProfileData.model_validate(user_profile).model_dump()

    async def update_user_profile(self, db: AsyncSession, profile_data: UserProfileData) -> UserProfile:
        stmt = select(UserProfile).where(UserProfile.user_id == profile_data.user_id)
        user_profile = (await db.execute(stmt)).scalar_one_or_none()
        if user_profile is None:
            profile_dict = profile_data.model_dump()
            profile_dict.pop("user_id", None)
            user_profile = UserProfile(user_id=profile_data.user_id, **profile_dict)
            await db.add(user_profile)
        else:
            for field, value in profile_data.model_dump().items():
                setattr(user_profile, field, value)
        await db.flush()
        return user_profile