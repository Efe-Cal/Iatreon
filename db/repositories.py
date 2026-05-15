from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date, datetime, timedelta
import uuid
from .models import IntakeSession, Article, SessionArticle, UserProfile
from .schemas import IntakeProfile, ArticleData

class IntakeRepo:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_session(self, user_id: uuid.UUID) -> IntakeSession:
        session = IntakeSession(user_id=user_id, status="in_progress", raw_transcript=[])
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def update_session(self, session_id: uuid.UUID, profile: IntakeProfile, transcript: list, medical_summary: str):
        session = await self.db.get(IntakeSession, session_id)
        session.chief_complaint = profile.chief_complaint
        session.symptoms = [s.model_dump() for s in profile.symptoms]
        session.red_flags = profile.red_flags
        session.medical_summary = medical_summary
        session.raw_transcript = transcript
        await self.db.commit()

    async def complete_session(self, session_id: uuid.UUID):
        session = await self.db.get(IntakeSession, session_id)
        session.status = "complete"
        session.completed_at = datetime.utcnow()
        await self.db.commit()


class ArticleRepo:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def upsert(self, data: ArticleData) -> Article:
        """Insert or update an article row and return it."""
        payload = {
            "pubmed_id": data.pubmed_id,
            "pmc_id": data.pmc_id,
            "doi": data.doi,
            "openalex_id": data.openalex_id,
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
            Article.pubmed_id == data.pubmed_id if data.pubmed_id else None,
            Article.pmc_id == data.pmc_id if data.pmc_id else None,
            Article.doi == data.doi if data.doi else None,
            Article.openalex_id == data.openalex_id if data.openalex_id else None,
        ]
        identity_filters = [clause for clause in identity_filters if clause is not None]

        existing = None
        if identity_filters:
            existing_stmt = select(Article).where(or_(*identity_filters))
            existing = (await self.db.execute(existing_stmt)).scalar_one_or_none()

        if existing is not None:
            for field, value in payload.items():
                setattr(existing, field, value)
            await self.db.commit()
            await self.db.refresh(existing)
            return existing

        article = Article(**payload)
        self.db.add(article)
        await self.db.commit()
        await self.db.refresh(article)
        return article

    async def get_cached(
        self,
        pubmed_id: str | None = None,
        pmc_id: str | None = None,
        doi: str | None = None,
        openalex_id: str | None = None,
        max_age_days: int = 30,
    ) -> Article | None:
        cutoff = datetime.utcnow() - timedelta(days=max_age_days)
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
        return (await self.db.execute(stmt)).scalar_one_or_none()
    
    async def link_to_session(self, session_id: uuid.UUID, article_id: uuid.UUID, query: str, quality_score: float):
        link = SessionArticle(
            session_id=session_id,
            article_id=article_id,
            query=query,
            quality_score=quality_score,
        )
        self.db.add(link)
        await self.db.commit()
        
    
    async def get_session_articles(self, session_id: uuid.UUID, limit: int = 8) -> list[Article]:
        stmt = (
            select(Article)
            .join(SessionArticle, SessionArticle.article_id == Article.id)
            .where(SessionArticle.session_id == session_id)
            .order_by(SessionArticle.quality_score.desc().nullslast())
            .limit(limit)
        )
        return list((await self.db.execute(stmt)).scalars())
