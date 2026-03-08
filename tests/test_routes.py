from __future__ import annotations
import json
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


@pytest.mark.asyncio
async def test_roi_summary_requires_api_key(app_client):
    response = await app_client.get("/api/roi/summary")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_viewer_forbidden_on_report_generate(app_client):
    response = await app_client.post(
        "/api/reports/generate",
        headers={"X-API-Key": "viewer-key"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_operator_can_generate_report(app_client):
    response = await app_client.post(
        "/api/reports/generate",
        headers={"X-API-Key": "operator-key"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "report_id" in data


@pytest.mark.asyncio
async def test_viewer_can_list_and_get_reports(app_client):
    create_resp = await app_client.post(
        "/api/reports/generate",
        headers={"X-API-Key": "operator-key"},
    )
    report_id = create_resp.json()["report_id"]

    list_resp = await app_client.get("/api/reports", headers={"X-API-Key": "viewer-key"})
    assert list_resp.status_code == 200
    assert any(item["report_id"] == report_id for item in list_resp.json()["items"])

    get_resp = await app_client.get(f"/api/reports/{report_id}", headers={"X-API-Key": "viewer-key"})
    assert get_resp.status_code == 200
    assert get_resp.json()["metadata"]["report_id"] == report_id


@pytest.mark.asyncio
async def test_reports_list_falls_back_to_index_when_db_empty(app_client, tmp_path, monkeypatch):
    index_path = tmp_path / "index.json"
    index_path.write_text(
        json.dumps(
            {
                "r1": {
                    "report_id": "r1",
                    "generated_at": "2026-03-03T10:00:00+00:00",
                    "files": [],
                    "from": "2026-03-01T00:00:00+00:00",
                    "to": "2026-03-03T00:00:00+00:00",
                    "format": "json",
                }
            }
        )
    )
    monkeypatch.setattr("app.routes_rest.REPORT_INDEX", index_path)
    with patch("app.routes_rest.list_executive_reports", new_callable=AsyncMock, return_value=[]):
        response = await app_client.get("/api/reports", headers={"X-API-Key": "viewer-key"})
    assert response.status_code == 200
    assert response.json()["items"][0]["report_id"] == "r1"


@pytest.mark.asyncio
async def test_get_report_falls_back_to_index_when_db_missing(app_client, tmp_path, monkeypatch):
    report_id = "fallback-report"
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    artifact = report_dir / f"{report_id}.json"
    artifact.write_text("{\"ok\": true}")

    index_path = report_dir / "index.json"
    index_path.write_text(
        json.dumps(
            {
                report_id: {
                    "report_id": report_id,
                    "generated_at": "2026-03-03T10:00:00+00:00",
                    "files": [str(artifact)],
                    "from": "2026-03-01T00:00:00+00:00",
                    "to": "2026-03-03T00:00:00+00:00",
                    "format": "json",
                }
            }
        )
    )
    monkeypatch.setattr("app.routes_rest.REPORT_INDEX", index_path)

    with patch("app.routes_rest.get_executive_report", new_callable=AsyncMock, return_value=None):
        response = await app_client.get(f"/api/reports/{report_id}", headers={"X-API-Key": "viewer-key"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["metadata"]["report_id"] == report_id
    assert len(payload["artifacts"]) == 1


@pytest.mark.asyncio
async def test_get_report_handles_corrupt_files_json(app_client):
    class CorruptModel:
        id = "db-corrupt"
        generated_at = None
        date_from = None
        date_to = None
        format = "both"
        files_json = "{not-valid-json"

    with patch("app.routes_rest.get_executive_report", new_callable=AsyncMock, return_value=CorruptModel()):
        response = await app_client.get("/api/reports/db-corrupt", headers={"X-API-Key": "viewer-key"})
    assert response.status_code == 200
    assert response.json()["metadata"]["files"] == []
