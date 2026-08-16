"""Async DB engine/session setup (task 0.5)."""

from collections.abc import AsyncGenerator

from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

def _async_url(url: str) -> str:
    """Force the asyncpg driver: hosted providers hand out plain
    postgres:// / postgresql:// URLs, which SQLAlchemy resolves to the
    sync psycopg2 driver."""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


engine = create_async_engine(_async_url(settings.database_url), echo=False, future=True)

async_session_factory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an async DB session per request."""
    async with async_session_factory() as session:
        yield session


async def init_db() -> None:
    """Create all tables. Sufficient for V1; swap for Alembic migrations later."""
    from app import models  # noqa: F401  (registers tables on SQLModel.metadata)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
