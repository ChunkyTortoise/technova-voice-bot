from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_health_returns_200(app_client):
    response = await app_client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data
    assert "services" in data


@pytest.mark.asyncio
async def test_create_session_returns_session_id(app_client):
    with patch("app.routes_rest.create_session", new_callable=AsyncMock):
        response = await app_client.post("/api/sessions")
        assert response.status_code == 201
        data = response.json()
        assert "session_id" in data
        assert "websocket_url" in data
        assert data["websocket_url"].startswith("/ws/audio/")
        # FIX #4: session_id is returned for localStorage persistence
        assert len(data["session_id"]) == 36  # UUID format


@pytest.mark.asyncio
async def test_get_history_unknown_session_returns_404(app_client):
    with patch("app.routes_rest.session_exists", return_value=False), \
         patch("app.routes_rest.get_session_history", return_value=[]):
        response = await app_client.get("/api/sessions/nonexistent-session/history")
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_history_returns_messages(app_client):
    fake_messages = [
        {"role": "user", "content": "Hello", "timestamp": "2026-03-01T10:00:00Z"},
        {"role": "assistant", "content": "Hi there!", "timestamp": "2026-03-01T10:00:01Z"},
    ]
    with patch("app.routes_rest.session_exists", return_value=True), \
         patch("app.routes_rest.get_session_history", return_value=fake_messages):
        response = await app_client.get("/api/sessions/test-session-id/history")
        assert response.status_code == 200
        data = response.json()
        assert len(data["messages"]) == 2
        assert data["messages"][0]["role"] == "user"
