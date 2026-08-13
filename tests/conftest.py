import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session_factory, init_db


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _ensure_tables():
    await init_db()


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    async with async_session_factory() as session:
        yield session
