import os

os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_arcscrow.db"
os.environ["SESSION_SECRET"] = "test-session-secret-that-is-long-enough"
os.environ["AI_PROVIDER"] = "development"
os.environ["CIRCLE_EMBEDDED_WALLET_ENABLED"] = "false"

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db.base import Base
from app.db.session import engine
from app.main import app


@pytest_asyncio.fixture(autouse=True)
async def reset_database():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as value:
        yield value
