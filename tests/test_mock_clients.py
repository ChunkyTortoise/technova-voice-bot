"""B1: Sanity-check mock patterns used throughout the test suite."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock


async def test_async_mock_returns_value():
    mock = AsyncMock(return_value="hello")
    result = await mock()
    assert result == "hello"


async def test_async_mock_side_effect_raises():
    mock = AsyncMock(side_effect=Exception("conn failed"))
    with pytest.raises(Exception, match="conn failed"):
        await mock()


async def test_async_mock_called_with_args():
    mock = AsyncMock(return_value=True)
    await mock("session-123", b"\x00\x01\x02")
    mock.assert_called_once_with("session-123", b"\x00\x01\x02")


async def test_async_mock_sequential_return_values():
    mock = AsyncMock(side_effect=["first", "second", "third"])
    assert await mock() == "first"
    assert await mock() == "second"
    assert await mock() == "third"


async def test_mock_context_manager_double_pattern():
    """Verify the double context manager pattern used for httpx streaming."""
    mock_response = AsyncMock()
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.stream = MagicMock(return_value=mock_response)

    async with mock_client as c:
        async with c.stream("POST", "http://x") as r:
            assert r is mock_response
