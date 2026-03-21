from __future__ import annotations
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db_session(rows=None):
    """Return a mock async context-manager DB session."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = rows or []
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_db)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm, mock_db


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_init_db_runs_create_all():
    """init_db calls create_all via a connection."""
    mock_conn = AsyncMock()
    mock_conn.run_sync = AsyncMock()

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_conn)
    cm.__aexit__ = AsyncMock(return_value=False)

    with patch("app.database.engine") as mock_engine:
        mock_engine.begin.return_value = cm
        from app.database import init_db
        await init_db()
        mock_conn.run_sync.assert_called_once()


# ---------------------------------------------------------------------------
# create_session
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_session_adds_and_commits():
    """create_session inserts a Session row and commits."""
    cm, mock_db = _make_db_session()

    with patch("app.database.AsyncSessionLocal", return_value=cm):
        from app.database import create_session
        await create_session("test-session-id")
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_create_session_uses_provided_id():
    """create_session stores the exact session_id passed in."""
    from app.database import Session as DBSession

    captured = {}
    cm, mock_db = _make_db_session()

    def capture_add(obj):
        captured["obj"] = obj

    mock_db.add = MagicMock(side_effect=capture_add)

    with patch("app.database.AsyncSessionLocal", return_value=cm):
        from app.database import create_session
        await create_session("my-unique-id")
        assert captured["obj"].id == "my-unique-id"


# ---------------------------------------------------------------------------
# save_message
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_message_adds_and_commits():
    """save_message inserts a Message row and commits."""
    cm, mock_db = _make_db_session()

    with patch("app.database.AsyncSessionLocal", return_value=cm):
        from app.database import save_message
        await save_message("sess-1", "user", "Hello world")
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_save_message_stores_role_and_content():
    """save_message persists the correct role and content."""
    from app.database import Message

    captured = {}
    cm, mock_db = _make_db_session()

    def capture_add(obj):
        captured["obj"] = obj

    mock_db.add = MagicMock(side_effect=capture_add)

    with patch("app.database.AsyncSessionLocal", return_value=cm):
        from app.database import save_message
        await save_message("sess-1", "assistant", "Hi there!")
        assert captured["obj"].role == "assistant"
        assert captured["obj"].content == "Hi there!"
        assert captured["obj"].session_id == "sess-1"


# ---------------------------------------------------------------------------
# get_session_history
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_session_history_returns_empty_list_when_no_messages():
    """get_session_history returns [] when no messages exist."""
    cm, _ = _make_db_session(rows=[])

    with patch("app.database.AsyncSessionLocal", return_value=cm):
        from app.database import get_session_history
        result = await get_session_history("sess-none")
        assert result == []


@pytest.mark.asyncio
async def test_get_session_history_serialises_messages():
    """get_session_history returns dicts with role, content, timestamp."""
    from datetime import datetime, timezone
    from app.database import Message

    ts = datetime(2026, 3, 1, 10, 0, 0, tzinfo=timezone.utc)
    fake_msg = MagicMock(spec=Message)
    fake_msg.role = "user"
    fake_msg.content = "Hello"
    fake_msg.timestamp = ts

    cm, mock_db = _make_db_session(rows=[fake_msg])

    with patch("app.database.AsyncSessionLocal", return_value=cm):
        from app.database import get_session_history
        result = await get_session_history("sess-1")
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "Hello"
        assert "2026-03-01" in result[0]["timestamp"]


@pytest.mark.asyncio
async def test_get_session_history_handles_null_timestamp():
    """get_session_history returns None for timestamp when unset."""
    from app.database import Message

    fake_msg = MagicMock(spec=Message)
    fake_msg.role = "user"
    fake_msg.content = "ping"
    fake_msg.timestamp = None

    cm, mock_db = _make_db_session(rows=[fake_msg])

    with patch("app.database.AsyncSessionLocal", return_value=cm):
        from app.database import get_session_history
        result = await get_session_history("sess-1")
        assert result[0]["timestamp"] is None
