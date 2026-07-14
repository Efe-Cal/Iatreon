import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    username: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    password_salt: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class PDFJob(Base):
    __tablename__ = "pdf_jobs"

    job_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


def database_url() -> str:
    return os.getenv(
        "BACKEND_API_DB_URL",
        "postgresql+asyncpg://backend_api:backend_api@localhost:5432/backend_api",
    )


engine = create_async_engine(database_url(), pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def db_session():
    async with SessionLocal() as db:
        yield db
