from __future__ import annotations
import asyncio
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    mock = AsyncMock()
    mock.ping = AsyncMock(return_value=True)
    mock.setex = AsyncMock(return_value=True)
    mock.set = AsyncMock(return_value=True)
    mock.get = AsyncMock(return_value=None)
    mock.exists = AsyncMock(return_value=1)
    mock.lrange = AsyncMock(return_value=[])
    mock.rpush = AsyncMock(return_value=1)
    mock.llen = AsyncMock(return_value=1)
    mock.expire = AsyncMock(return_value=True)
    mock.delete = AsyncMock(return_value=1)
    mock.aclose = AsyncMock()
    return mock


@pytest_asyncio.fixture
async def app_client():
    """Async test client with mocked external services."""
    with patch("app.session_manager.get_redis") as mock_get_redis, \
         patch("app.session_manager._redis_client", new=None), \
         patch("app.database.init_db", new_callable=AsyncMock), \
         patch("app.database.create_session", new_callable=AsyncMock), \
         patch("app.database.save_message", new_callable=AsyncMock), \
         patch("app.database.get_session_history", return_value=[]):

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.setex = AsyncMock(return_value=True)
        mock_redis.exists = AsyncMock(return_value=1)
        mock_redis.lrange = AsyncMock(return_value=[])
        mock_redis.rpush = AsyncMock(return_value=1)
        mock_redis.llen = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock(return_value=True)
        mock_redis.delete = AsyncMock(return_value=1)
        mock_redis.aclose = AsyncMock()
        mock_get_redis.return_value = mock_redis

        from app.main import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
