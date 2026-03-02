from __future__ import annotations
import json
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_create_session():
    mock_redis = AsyncMock()
    mock_redis.setex = AsyncMock(return_value=True)
    mock_redis.delete = AsyncMock(return_value=1)

    with patch("app.session_manager.get_redis", return_value=mock_redis), \
         patch("app.session_manager.db_create_session", new_callable=AsyncMock):
        from app.session_manager import create_session
        result = await create_session("test-session-123")
        assert result["session_id"] == "test-session-123"
        assert "created_at" in result


@pytest.mark.asyncio
async def test_append_message():
    mock_redis = AsyncMock()
    mock_redis.rpush = AsyncMock(return_value=1)
    mock_redis.expire = AsyncMock(return_value=True)
    mock_redis.llen = AsyncMock(return_value=1)

    with patch("app.session_manager.get_redis", return_value=mock_redis), \
         patch("app.session_manager.save_message", new_callable=AsyncMock):
        from app.session_manager import append_message
        await append_message("test-session-123", "user", "Hello")
        mock_redis.rpush.assert_called_once()


@pytest.mark.asyncio
async def test_get_conversation_empty():
    mock_redis = AsyncMock()
    mock_redis.lrange = AsyncMock(return_value=[])

    with patch("app.session_manager.get_redis", return_value=mock_redis):
        from app.session_manager import get_conversation
        result = await get_conversation("test-session-123")
        assert result == []


@pytest.mark.asyncio
async def test_get_conversation_with_messages():
    msg = json.dumps({"role": "user", "content": "Hi", "timestamp": "2026-03-01T10:00:00Z"})
    mock_redis = AsyncMock()
    mock_redis.lrange = AsyncMock(return_value=[msg])

    with patch("app.session_manager.get_redis", return_value=mock_redis):
        from app.session_manager import get_conversation
        result = await get_conversation("test-session-123")
        assert len(result) == 1
        assert result[0]["role"] == "user"


@pytest.mark.asyncio
async def test_acquire_redis_lock_success():
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)

    with patch("app.session_manager.get_redis", return_value=mock_redis):
        from app.session_manager import acquire_redis_lock
        result = await acquire_redis_lock("test-session-123")
        assert result is True


@pytest.mark.asyncio
async def test_acquire_redis_lock_fails_when_locked():
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=None)  # NX fails = lock held

    with patch("app.session_manager.get_redis", return_value=mock_redis):
        from app.session_manager import acquire_redis_lock
        result = await acquire_redis_lock("test-session-123")
        assert result is False


@pytest.mark.asyncio
async def test_release_redis_lock():
    mock_redis = AsyncMock()
    mock_redis.delete = AsyncMock(return_value=1)

    with patch("app.session_manager.get_redis", return_value=mock_redis):
        from app.session_manager import release_redis_lock
        await release_redis_lock("test-session-123")
        mock_redis.delete.assert_called_once_with("session:test-session-123:lock")


@pytest.mark.asyncio
async def test_session_lock_per_session():
    """FIX #9: Verify each session gets its own asyncio.Lock."""
    from app.session_manager import get_session_lock
    lock_a = await get_session_lock("session-a")
    lock_b = await get_session_lock("session-b")
    assert lock_a is not lock_b
    # Same session gets same lock
    lock_a2 = await get_session_lock("session-a")
    assert lock_a is lock_a2
