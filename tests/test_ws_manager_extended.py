from __future__ import annotations
import pytest
from unittest.mock import AsyncMock
from app.ws_manager import WebSocketManager


def _make_ws() -> AsyncMock:
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_bytes = AsyncMock()
    ws.send_text = AsyncMock()
    return ws


# ---------------------------------------------------------------------------
# Connection limit (MAX_CONCURRENT_WS_PER_IP = 5)
# ---------------------------------------------------------------------------

async def test_connection_count_zero_for_unknown_ip():
    """An IP with no connections reports count of 0."""
    manager = WebSocketManager()
    assert manager.get_connection_count_for_ip("192.168.1.1") == 0


async def test_connection_limit_five_per_ip():
    """Up to 5 sessions can be registered from a single IP."""
    manager = WebSocketManager()
    ip = "10.0.0.5"
    for i in range(5):
        ws = _make_ws()
        sid = f"sess-{i}"
        await manager.connect(sid, ws)
        manager.register_ip(sid, ip)

    assert manager.get_connection_count_for_ip(ip) == 5


async def test_sixth_connection_exceeds_limit():
    """A 6th connection from the same IP exceeds the allowed limit of 5."""
    from app.config import settings
    manager = WebSocketManager()
    ip = "10.0.0.6"
    for i in range(6):
        ws = _make_ws()
        sid = f"sess-{i}"
        await manager.connect(sid, ws)
        manager.register_ip(sid, ip)

    count = manager.get_connection_count_for_ip(ip)
    assert count > settings.MAX_CONCURRENT_WS_PER_IP


async def test_disconnect_all_sessions_clears_ip_count():
    """Disconnecting all sessions from an IP resets count to 0."""
    manager = WebSocketManager()
    ip = "10.0.0.7"
    sessions = [f"sess-{i}" for i in range(3)]
    for sid in sessions:
        ws = _make_ws()
        await manager.connect(sid, ws)
        manager.register_ip(sid, ip)

    assert manager.get_connection_count_for_ip(ip) == 3

    for sid in sessions:
        await manager.disconnect(sid)

    assert manager.get_connection_count_for_ip(ip) == 0


async def test_disconnect_one_of_many_reduces_count_by_one():
    """Disconnecting one session reduces IP count by exactly 1."""
    manager = WebSocketManager()
    ip = "10.0.0.8"
    for i in range(3):
        ws = _make_ws()
        sid = f"sess-{i}"
        await manager.connect(sid, ws)
        manager.register_ip(sid, ip)

    await manager.disconnect("sess-1")
    assert manager.get_connection_count_for_ip(ip) == 2


# ---------------------------------------------------------------------------
# Session cleanup on disconnect
# ---------------------------------------------------------------------------

async def test_disconnect_removes_from_connections_map():
    """After disconnect the session is not in _connections."""
    manager = WebSocketManager()
    ws = _make_ws()
    await manager.connect("cleanup-sess", ws)
    assert manager.is_connected("cleanup-sess")
    await manager.disconnect("cleanup-sess")
    assert not manager.is_connected("cleanup-sess")


async def test_disconnect_removes_ip_mapping():
    """After disconnect the session is removed from _session_ip."""
    manager = WebSocketManager()
    ws = _make_ws()
    await manager.connect("map-sess", ws)
    manager.register_ip("map-sess", "172.16.0.1")
    await manager.disconnect("map-sess")
    assert "map-sess" not in manager._session_ip


async def test_disconnect_removes_session_from_ip_set():
    """After disconnect the session_id is removed from the IP's session set."""
    manager = WebSocketManager()
    ws = _make_ws()
    await manager.connect("ip-set-sess", ws)
    manager.register_ip("ip-set-sess", "172.16.0.2")
    await manager.disconnect("ip-set-sess")
    assert "ip-set-sess" not in manager._ip_sessions.get("172.16.0.2", set())


async def test_disconnect_nonexistent_session_is_safe():
    """Disconnecting a session that was never connected does not raise."""
    manager = WebSocketManager()
    await manager.disconnect("ghost-session")  # Must not raise


async def test_double_disconnect_is_idempotent():
    """Disconnecting a session twice is safe and leaves count at 0."""
    manager = WebSocketManager()
    ws = _make_ws()
    await manager.connect("dbl-sess", ws)
    manager.register_ip("dbl-sess", "10.1.1.1")
    await manager.disconnect("dbl-sess")
    await manager.disconnect("dbl-sess")  # second call must not raise
    assert manager.get_connection_count_for_ip("10.1.1.1") == 0


async def test_send_event_swallows_exceptions():
    """send_event logs but does not propagate WebSocket errors."""
    manager = WebSocketManager()
    ws = _make_ws()
    ws.send_text = AsyncMock(side_effect=RuntimeError("closed"))
    await manager.connect("err-sess", ws)
    await manager.send_event("err-sess", {"type": "test"})  # Must not raise


async def test_manager_handles_multiple_ips_independently():
    """Sessions from different IPs are tracked separately."""
    manager = WebSocketManager()
    for i, ip in enumerate(["1.1.1.1", "2.2.2.2", "3.3.3.3"]):
        ws = _make_ws()
        sid = f"sess-ip-{i}"
        await manager.connect(sid, ws)
        manager.register_ip(sid, ip)

    assert manager.get_connection_count_for_ip("1.1.1.1") == 1
    assert manager.get_connection_count_for_ip("2.2.2.2") == 1
    assert manager.get_connection_count_for_ip("3.3.3.3") == 1

    await manager.disconnect("sess-ip-0")
    assert manager.get_connection_count_for_ip("1.1.1.1") == 0
    assert manager.get_connection_count_for_ip("2.2.2.2") == 1
