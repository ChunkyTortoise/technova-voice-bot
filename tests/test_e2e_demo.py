"""B7: End-to-end demo-mode endpoint tests (no API keys required)."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, patch


async def test_health_returns_200(app_client):
    response = await app_client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


async def test_health_has_version(app_client):
    response = await app_client.get("/api/health")
    data = response.json()
    assert "version" in data
    assert isinstance(data["version"], str)


async def test_health_has_services(app_client):
    response = await app_client.get("/api/health")
    data = response.json()
    assert "services" in data
    services = data["services"]
    assert "database" in services
    assert "deepgram" in services
    assert "anthropic" in services


async def test_demo_status_endpoint(app_client):
    response = await app_client.get("/api/demo-status")
    assert response.status_code == 200
    data = response.json()
    assert "demo_mode" in data
    assert "deepgram_configured" in data
    assert "anthropic_configured" in data


async def test_demo_status_reflects_missing_keys(app_client):
    """With no API keys set, demo_mode should be True."""
    response = await app_client.get("/api/demo-status")
    data = response.json()
    # In test env no keys are configured
    assert data["demo_mode"] is True


async def test_create_session_returns_uuid(app_client):
    with patch("app.routes_rest.create_session", new_callable=AsyncMock):
        response = await app_client.post("/api/sessions")
    assert response.status_code == 201
    data = response.json()
    assert "session_id" in data
    assert len(data["session_id"]) == 36  # UUID


async def test_create_session_has_websocket_url(app_client):
    with patch("app.routes_rest.create_session", new_callable=AsyncMock):
        response = await app_client.post("/api/sessions")
    data = response.json()
    assert data["websocket_url"].startswith("/ws/audio/")


async def test_roi_summary_requires_auth(app_client):
    response = await app_client.get("/api/roi/summary")
    assert response.status_code == 401
