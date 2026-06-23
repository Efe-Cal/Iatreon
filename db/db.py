from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, MappedAsDataclass
import os
from contextlib import asynccontextmanager
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://app:app@localhost:5432/app")

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=1800,
)

SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

@asynccontextmanager
async def unit_of_work():
    """One session, one transaction. Commits on success, rolls back on error."""
    async with SessionLocal() as db:
        async with db.begin():
            yield db

@asynccontextmanager
async def read_only_session():
    """For read-only operations — no transaction overhead needed."""
    async with SessionLocal() as db:
        yield db

class Base(MappedAsDataclass, DeclarativeBase):
    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class CheckpointerManager:
    def __init__(self):
        self._saver: AsyncPostgresSaver | None = None

    async def init_pool(self):
        langgraph_url = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql+psycopg://")
        
        self._context = AsyncPostgresSaver.from_conn_string(langgraph_url)
        self._saver = await self._context.__aenter__()
        await self._saver.setup()

    async def close_pool(self):
        if self._context:
            await self._context.__aexit__(None, None, None)

    def get_checkpointer(self) -> AsyncPostgresSaver:
        if self._saver is None:
            raise RuntimeError("CheckpointerManager is not initialized. Did you run init_pool()?")
        return self._saver

# Single manager for all
checkpointer_manager = CheckpointerManager()
