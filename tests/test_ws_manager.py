"""B2: WebSocketManager connect/disconnect/send lifecycle tests."""
from __future__ import annotations
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.ws_manager import WebSocketManager


def _make_ws() -> AsyncMock:
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_bytes = AsyncMock()
    ws.send_text = AsyncMock()
    return ws


async def test_connect_accepts_websocket():
    manager = WebSocketManager()
    ws = _make_ws()
    await manager.connect("sess-1", ws)
    ws.accept.assert_called_once()
    assert manager.is_connected("sess-1")


async def test_disconnect_removes_session():
    manager = WebSocketManager()
    ws = _make_ws()
    await manager.connect("sess-1", ws)
    await manager.disconnect("sess-1")
    assert not manager.is_connected("sess-1")


async def test_send_audio_calls_send_bytes():
    manager = WebSocketManager()
    ws = _make_ws()
    await manager.connect("sess-1", ws)
    payload = b"\x00\x01\x02\x03"
    await manager.send_audio("sess-1", payload)
    ws.send_bytes.assert_called_once_with(payload)


async def test_send_event_serialises_to_json():
    manager = WebSocketManager()
    ws = _make_ws()
    await manager.connect("sess-1", ws)
    event = {"type": "transcript", "text": "hello"}
    await manager.send_event("sess-1", event)
    ws.send_text.assert_called_once_with(json.dumps(event))


async def test_send_to_missing_session_is_noop():
    manager = WebSocketManager()
    # Should not raise even though session never connected
    await manager.send_audio("ghost", b"\x00")
    await manager.send_event("ghost", {"type": "ping"})


async def test_send_audio_swallows_exceptions():
    manager = WebSocketManager()
    ws = _make_ws()
    ws.send_bytes = AsyncMock(side_effect=RuntimeError("broken pipe"))
    await manager.connect("sess-1", ws)
    # Must not raise
    await manager.send_audio("sess-1", b"\x00")


async def test_register_ip_and_count():
    manager = WebSocketManager()
    ws = _make_ws()
    await manager.connect("sess-1", ws)
    manager.register_ip("sess-1", "10.0.0.1")
    assert manager.get_connection_count_for_ip("10.0.0.1") == 1


async def test_multiple_sessions_same_ip():
    manager = WebSocketManager()
    ws1 = _make_ws()
    ws2 = _make_ws()
    await manager.connect("sess-1", ws1)
    await manager.connect("sess-2", ws2)
    manager.register_ip("sess-1", "10.0.0.1")
    manager.register_ip("sess-2", "10.0.0.1")
    assert manager.get_connection_count_for_ip("10.0.0.1") == 2


async def test_disconnect_reduces_ip_count():
    manager = WebSocketManager()
    ws = _make_ws()
    await manager.connect("sess-1", ws)
    manager.register_ip("sess-1", "10.0.0.1")
    await manager.disconnect("sess-1")
    assert manager.get_connection_count_for_ip("10.0.0.1") == 0


async def test_is_connected_false_before_connect():
    manager = WebSocketManager()
    assert not manager.is_connected("nobody")
