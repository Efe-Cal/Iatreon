from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value
from datetime import datetime, timedelta
import uuid
from .models import (
    DoctorSession,
    IntakeSession,
    Article,
    ResearchSession,
    SessionArticle,
    BookSection,
    SessionBookSection,
    User,
    UserProfile,
    ChatSession,
    WebSearchResult,
    SessionWebSearchResult,
)
from .schemas import BookSectionData, IntakeProfile, ArticleData, UserProfileData
from .crypto import decrypt_json, encrypt_json, new_data_key, unwrap_data_key, wrap_data_key, zero_bytes


async def _get_user_data_key(db: AsyncSession, user_id: uuid.UUID) -> bytearray:
    if isinstance(user_id, str):
        user_id = uuid.UUID(user_id)
    user = await db.get(User, user_id)
    if user is None:
        raise ValueError('user not found')
    if not user.encrypted_data_key:
        data_key = new_data_key()
        try:
            user.encrypted_data_key = wrap_data_key(data_key, user.id)
        finally:
            zero_bytes(data_key)
        await db.flush()
    return unwrap_data_key(user.encrypted_data_key, user.id)


async def _encrypt_record_payload(db: AsyncSession, user_id: uuid.UUID, purpose: str, payload: dict) -> str:
    data_key = await _get_user_data_key(db, user_id)
    try:
        return encrypt_json(data_key, user_id, purpose, payload)
    finally:
        zero_bytes(data_key)


async def _decrypt_record_payload(db: AsyncSession, user_id: uuid.UUID, purpose: str, encrypted_payload: str) -> dict:
    data_key = await _get_user_data_key(db, user_id)
    try:
        return decrypt_json(data_key, user_id, purpose, encrypted_payload)
    finally:
        zero_bytes(data_key)


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

    async def _hydrate_session(self, db: AsyncSession, session: IntakeSession | None) -> IntakeSession | None:
        if session is None or not session.encrypted_payload:
            return session
        payload = await _decrypt_record_payload(db, self.user_id, f'intake-session:{session.id}', session.encrypted_payload)
        for field in ('chief_complaint', 'symptoms', 'red_flags', 'medical_summary', 'thread_id', 'status', 'completed_at'):
            if field in payload:
                set_committed_value(session, field, payload[field])
        return session

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
        session = IntakeSession(user_id=self.user_id, status="in_progress")
        db.add(session)
        await db.flush()
        return session

    async def get_or_create_session(self, db: AsyncSession, session_id: uuid.UUID) -> IntakeSession:
        session = await db.get(IntakeSession, session_id)
        if session:
            if session.user_id != self.user_id:
                raise ValueError("Unauthorized: User ID mismatch")
            return session
        
        session = IntakeSession(id=session_id, user_id=self.user_id, status="in_progress")
        db.add(session)
        await db.flush()
        return session

    async def update_session(self, db: AsyncSession, session_id: uuid.UUID, profile: IntakeProfile, conversation_thread_id: str):
        session = await db.get(IntakeSession, session_id)
        if session.user_id != self.user_id:
            return "Error: Unauthorized"
        session.encrypted_payload = await _encrypt_record_payload(
            db,
            self.user_id,
            f'intake-session:{session.id}',
            {
                'chief_complaint': profile.chief_complaint,
                'symptoms': [s.model_dump() for s in profile.symptoms],
                'red_flags': profile.red_flags,
                'medical_summary': profile.medical_summary,
                'thread_id': conversation_thread_id,
                'status': session.status,
                'completed_at': session.completed_at,
            },
        )
        session.chief_complaint = None
        session.symptoms = []
        session.red_flags = []
        session.medical_summary = None
        session.thread_id = None
        await db.flush()
        return "OK"

    async def complete_session(self, db: AsyncSession, session_id: uuid.UUID):
        session = await db.get(IntakeSession, session_id)
        if session.user_id != self.user_id:
            return "Error: Unauthorized"
        session.status = "complete"
        session.completed_at = datetime.utcnow()
        if session.encrypted_payload:
            payload = await _decrypt_record_payload(db, self.user_id, f'intake-session:{session.id}', session.encrypted_payload)
            payload['status'] = session.status
            payload['completed_at'] = session.completed_at
            session.encrypted_payload = await _encrypt_record_payload(db, self.user_id, f'intake-session:{session.id}', payload)
        await db.flush()
        return "OK"

    async def get_session(self, db: AsyncSession, session_id: uuid.UUID) -> IntakeSession | None:
        if isinstance(session_id, str):
            session_id = uuid.UUID(session_id)

        session = await db.get(IntakeSession, session_id)
        if session and session.user_id == self.user_id:
            return await self._hydrate_session(db, session)
        return None

class ResearchRepo:
    def __init__(self, user_id: str):
        self.user_id = uuid.UUID(user_id)

    async def _hydrate_session(self, db: AsyncSession, session: ResearchSession | None) -> ResearchSession | None:
        if session is None or not session.encrypted_payload:
            return session
        payload = await _decrypt_record_payload(db, self.user_id, f'research-session:{session.id}', session.encrypted_payload)
        for field in ('research_report', 'citations'):
            if field in payload:
                set_committed_value(session, field, payload[field])
        return session

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
            set_committed_value(session, 'research_report', research_report)
        if citations is not None:
            set_committed_value(session, 'citations', citations)

        session.encrypted_payload = await _encrypt_record_payload(
            db,
            self.user_id,
            f'research-session:{session.id}',
            {
                'research_report': session.research_report,
                'citations': session.citations,
            },
        )
        session.research_report = None
        session.citations = {}

        await db.flush()
        return session

    async def get_research_session(self, db: AsyncSession, session_id: uuid.UUID) -> ResearchSession | None:
        if isinstance(session_id, str):
            session_id = uuid.UUID(session_id)
        
        session = await db.get(ResearchSession, session_id)
        if session and session.user_id == self.user_id:
            return await self._hydrate_session(db, session)
        return None

    async def get_research_session_by_intake_id(self, db: AsyncSession, intake_session_id: uuid.UUID) -> ResearchSession | None:
        if isinstance(intake_session_id, str):
            intake_session_id = uuid.UUID(intake_session_id)

        stmt = select(ResearchSession).where(
            ResearchSession.intake_session_id == intake_session_id,
            ResearchSession.user_id == self.user_id,
        )
        return await self._hydrate_session(db, (await db.execute(stmt)).scalar_one_or_none())

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
        db.add(article)
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
        db.add(section)
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
        db.add(link)
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
        db.add(result)
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
        db.add(link)
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
        db.add(user)
        await db.flush()
        return user

    async def get_user_id_by_ssh_key(self, db: AsyncSession, ssh_key: str) -> uuid.UUID | None:
        stmt = select(User.id).where(User.ssh_key == ssh_key)
        return (await db.execute(stmt)).scalar_one_or_none()

    async def has_user_profile(self, db: AsyncSession, user_id: uuid.UUID) -> bool:
        stmt = select(UserProfile.user_id).where(UserProfile.user_id == user_id)
        return (await db.execute(stmt)).scalar_one_or_none() is not None

    async def initialize_user_encryption(self, db: AsyncSession, user_id: uuid.UUID) -> None:
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)
        user = await db.get(User, user_id)
        if user is None:
            raise ValueError('user not found')
        if user.encrypted_data_key:
            unwrap_data_key(user.encrypted_data_key, user.id)
            return
        data_key = new_data_key()
        try:
            user.encrypted_data_key = wrap_data_key(data_key, user.id)
        finally:
            zero_bytes(data_key)
        await db.flush()

    async def _get_user_data_key(self, db: AsyncSession, user_id: uuid.UUID) -> bytearray:
        return await _get_user_data_key(db, user_id)
    
    async def get_user_profile(self, db: AsyncSession, user_id: uuid.UUID) -> dict:
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)
        stmt = select(UserProfile).where(UserProfile.user_id == user_id)
        user_profile = (await db.execute(stmt)).scalar_one_or_none()
        if user_profile is None:
            return {}
        if user_profile.encrypted_payload:
            data_key = await self._get_user_data_key(db, user_id)
            try:
                return decrypt_json(data_key, user_id, 'user-profile', user_profile.encrypted_payload)
            finally:
                zero_bytes(data_key)
        return UserProfileData.model_validate(user_profile).model_dump()

    async def update_user_profile(self, db: AsyncSession, profile_data: UserProfileData) -> UserProfile:
        stmt = select(UserProfile).where(UserProfile.user_id == profile_data.user_id)
        user_profile = (await db.execute(stmt)).scalar_one_or_none()
        profile_dict = profile_data.model_dump()
        data_key = await self._get_user_data_key(db, profile_data.user_id)
        try:
            encrypted_payload = encrypt_json(data_key, profile_data.user_id, 'user-profile', profile_dict)
        finally:
            zero_bytes(data_key)
        if user_profile is None:
            user_profile = UserProfile(user_id=profile_data.user_id, encrypted_payload=encrypted_payload)
            db.add(user_profile)
        else:
            user_profile.encrypted_payload = encrypted_payload
            user_profile.demographics = None
            user_profile.pmh = []
            user_profile.medications = []
            user_profile.allergies = []
            user_profile.family_history = []
            user_profile.social = None
            user_profile.medical_summary = None
        await db.flush()
        return user_profile

class SessionRepo:
    async def create_session(self, db: AsyncSession, user_id: uuid.UUID) -> ChatSession:
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)
        session = ChatSession(user_id=user_id)
        db.add(session)
        await db.flush()
        return session

    async def get_session(self, db: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID) -> ChatSession | None:
        if isinstance(session_id, str):
            session_id = uuid.UUID(session_id)
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)
        session = await db.get(ChatSession, session_id)
        if session is None or session.user_id != user_id:
            return None
        return session
    
    async def link_session(self, db: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID, session_to_link: IntakeSession | ResearchSession | DoctorSession) -> ChatSession:
        session = await self.get_session(db, user_id, session_id)
        if session is None:
            return None
        
        if isinstance(session_to_link, IntakeSession):
            session.intake_session_id = session_to_link.id
        elif isinstance(session_to_link, ResearchSession):
            session.research_session_id = session_to_link.id
        else:
            raise ValueError("Invalid session type to link")
        
        await db.flush()
        return session
    
class DoctorRepo:
    async def create_doctor_session(self, db: AsyncSession, user_id: uuid.UUID, chat_session_id: uuid.UUID, thread_id: str) -> DoctorSession:
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)
        if isinstance(chat_session_id, str):
            chat_session_id = uuid.UUID(chat_session_id)
        session = DoctorSession(user_id=user_id, chat_session_id=chat_session_id, thread_id=thread_id)
        db.add(session)
        await db.flush()
        return session

    async def get_doctor_session(self, db: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID) -> DoctorSession | None:
        if isinstance(session_id, str):
            session_id = uuid.UUID(session_id)
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)
        session = await db.get(DoctorSession, session_id)
        if session is None or session.user_id != user_id:
            return None
        return session
