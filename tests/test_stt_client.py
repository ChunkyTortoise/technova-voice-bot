"""B3: DeepgramSTTClient unit tests — no real Deepgram SDK required."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


async def test_init_stores_callback():
    from app.stt_client import DeepgramSTTClient

    callback = AsyncMock()
    client = DeepgramSTTClient(on_transcript=callback)
    assert client.on_transcript is callback
    assert client._connected is False
    assert client._connection is None


async def test_send_audio_no_op_when_not_connected():
    from app.stt_client import DeepgramSTTClient

    client = DeepgramSTTClient(on_transcript=AsyncMock())
    # Should not raise even though _connection is None
    await client.send_audio(b"\x00\x01")


async def test_send_audio_calls_connection_send():
    from app.stt_client import DeepgramSTTClient

    mock_conn = AsyncMock()
    mock_conn.send = AsyncMock()
    client = DeepgramSTTClient(on_transcript=AsyncMock())
    client._connection = mock_conn
    client._connected = True
    await client.send_audio(b"\xAB\xCD")
    mock_conn.send.assert_called_once_with(b"\xAB\xCD")


async def test_disconnect_calls_finish():
    from app.stt_client import DeepgramSTTClient

    mock_conn = AsyncMock()
    mock_conn.finish = AsyncMock()
    client = DeepgramSTTClient(on_transcript=AsyncMock())
    client._connection = mock_conn
    client._connected = True
    await client.disconnect()
    mock_conn.finish.assert_called_once()
    assert client._connected is False


async def test_disconnect_swallows_exception():
    from app.stt_client import DeepgramSTTClient

    mock_conn = AsyncMock()
    mock_conn.finish = AsyncMock(side_effect=RuntimeError("network error"))
    client = DeepgramSTTClient(on_transcript=AsyncMock())
    client._connection = mock_conn
    client._connected = True
    # Must not raise
    await client.disconnect()
    assert client._connected is False


async def test_disconnect_noop_when_no_connection():
    from app.stt_client import DeepgramSTTClient

    client = DeepgramSTTClient(on_transcript=AsyncMock())
    # Should not raise
    await client.disconnect()
