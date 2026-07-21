from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Test settings must be in place before anything imports app.config (which
# reads required env vars at Settings() construction time).
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://workshopos:workshopos@localhost:55432/workshopos_test")
os.environ.setdefault("JWT_SECRET", "test-secret-do-not-use-in-prod")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.db import get_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models import ENTERPRISE_PLAN_ID, FREE_PLAN_ID, PRO_PLAN_ID, Base, Plan  # noqa: E402

TEST_DATABASE_URL = os.environ["DATABASE_URL"]

engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
TestSessionFactory = async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _prepare_database():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with TestSessionFactory() as session:
        session.add_all(
            [
                Plan(
                    id=FREE_PLAN_ID,
                    key="free",
                    name="Free",
                    max_shops=1,
                    max_toolboxes=1,
                    max_drawers=10,
                    max_tools=100,
                    max_users=1,
                ),
                Plan(
                    id=PRO_PLAN_ID,
                    key="pro",
                    name="Pro",
                    max_shops=1,
                    max_toolboxes=None,
                    max_drawers=None,
                    max_tools=None,
                    max_users=None,
                ),
                Plan(
                    id=ENTERPRISE_PLAN_ID,
                    key="enterprise",
                    name="Enterprise",
                    max_shops=None,
                    max_toolboxes=None,
                    max_drawers=None,
                    max_tools=None,
                    max_users=None,
                ),
            ]
        )
        await session.commit()
    yield
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _clean_tables():
    """Truncate all app tables except plans between tests, keeping seed data."""
    yield
    async with engine.begin() as conn:
        table_names = [t.name for t in Base.metadata.sorted_tables if t.name != "plans"]
        if table_names:
            await conn.execute(text(f"TRUNCATE TABLE {', '.join(table_names)} RESTART IDENTITY CASCADE"))


async def _override_get_session() -> AsyncIterator[AsyncSession]:
    async with TestSessionFactory() as session:
        yield session


app.dependency_overrides[get_session] = _override_get_session


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    async with TestSessionFactory() as session:
        yield session


async def register_org(client: AsyncClient, *, org_name: str | None = None, email: str | None = None) -> dict:
    """Helper: registers a fresh org+user and returns the RegisterResponse JSON."""
    suffix = uuid.uuid4().hex[:8]
    payload = {
        "organization_name": org_name or f"Test Org {suffix}",
        "email": email or f"user-{suffix}@example.com",
        "password": "correct-horse-battery-staple",
        "display_name": "Test User",
    }
    response = await client.post("/auth/register", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
