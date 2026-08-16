import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import async_session_factory, init_db

TEST_EMAIL = "testuser@example.com"


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _ensure_tables():
    await init_db()


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    async with async_session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def test_user(db_session):
    from app.repository import get_or_create_dev_user

    return await get_or_create_dev_user(db_session, TEST_EMAIL)


@pytest_asyncio.fixture
async def auth_client():
    """ASGI client already logged in as the shared test user (via dev-login);
    the auth cookie persists on the client for subsequent requests."""
    from main import app

    original_dev_auth = settings.dev_auth
    settings.dev_auth = True
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post("/auth/dev-login", json={"email": TEST_EMAIL})
            assert resp.status_code == 200, resp.text
            yield c
    finally:
        settings.dev_auth = original_dev_auth
