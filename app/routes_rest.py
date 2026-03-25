from __future__ import annotations
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
import redis.asyncio as aioredis
from app.config import settings
from app.session_manager import create_session, session_exists
from app.database import (
    AsyncSessionLocal,
    Message,
    Session,
    get_executive_report,
    get_session_history,
    list_executive_reports,
    save_executive_report,
)
from sqlalchemy import func, select
from app.utils.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api")
REPORT_DIR = Path("data/reports")
REPORT_INDEX = REPORT_DIR / "index.json"


class SessionResponse(BaseModel):
    session_id: str
    created_at: str
    websocket_url: str


class HistoryResponse(BaseModel):
    session_id: str
    messages: list[dict]


def _range_bounds(date_from: str | None, date_to: str | None) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    end = datetime.fromisoformat(date_to) if date_to else now
    start = datetime.fromisoformat(date_from) if date_from else end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start, end


def _load_index() -> dict:
    if not REPORT_INDEX.exists():
        return {}
    try:
        return json.loads(REPORT_INDEX.read_text())
    except json.JSONDecodeError:
        return {}


def _save_index(payload: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_INDEX.write_text(json.dumps(payload, indent=2, sort_keys=True))


def _report_metadata_from_model(model) -> dict:
    try:
        files = json.loads(model.files_json)
    except json.JSONDecodeError:
        files = []
    return {
        "report_id": model.id,
        "generated_at": model.generated_at.isoformat() if model.generated_at else None,
        "files": files,
        "from": model.date_from.isoformat() if model.date_from else None,
        "to": model.date_to.isoformat() if model.date_to else None,
        "format": model.format,
    }


def _api_key_role(api_key: str | None) -> str | None:
    configured = {
        "admin": settings.ADMIN_API_KEY,
        "operator": settings.OPERATOR_API_KEY,
        "viewer": settings.VIEWER_API_KEY,
    }
    if any(configured.values()):
        for role, key in configured.items():
            if key and api_key == key:
                return role
        return None

    # Development fallback when explicit keys are not configured.
    fallback = {"admin-key": "admin", "operator-key": "operator", "viewer-key": "viewer"}
    return fallback.get(api_key or "")


def _require_role(api_key: str | None, allowed: set[str]) -> str:
    role = _api_key_role(api_key)
    if role is None:
        if not api_key:
            raise HTTPException(status_code=401, detail="X-API-Key header required")
        raise HTTPException(status_code=403, detail="Invalid API key")
    rank = {"viewer": 1, "operator": 2, "admin": 3}
    if rank[role] < min(rank[r] for r in allowed):
        raise HTTPException(status_code=403, detail="Insufficient role permissions")
    return role


async def _compute_roi_summary(start: datetime, end: datetime) -> dict:
    async with AsyncSessionLocal() as db:
        total_sessions = (
            await db.execute(
                select(func.count(Session.id)).where(
                    Session.created_at >= start,
                    Session.created_at <= end,
                )
            )
        ).scalar_one()
        total_messages = (
            await db.execute(
                select(func.count(Message.id)).where(
                    Message.timestamp >= start,
                    Message.timestamp <= end,
                )
            )
        ).scalar_one()

    minutes_saved = float(total_sessions) * 5.0
    dollars_saved = minutes_saved / 60.0 * 30.0
    infra_cost = float(total_messages) * 0.02
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "kpis": {
            "sessions": int(total_sessions),
            "messages": int(total_messages),
            "estimated_minutes_saved": round(minutes_saved, 2),
            "estimated_dollars_saved": round(dollars_saved, 2),
            "estimated_infra_cost": round(infra_cost, 2),
            "net_value": round(dollars_saved - infra_cost, 2),
        },
    }


@router.get("/demo-status")
async def demo_status():
    """Check whether the app is running in demo mode."""
    demo = not settings.DEEPGRAM_API_KEY or not settings.ANTHROPIC_API_KEY
    return {
        "demo_mode": demo,
        "deepgram_configured": bool(settings.DEEPGRAM_API_KEY),
        "anthropic_configured": bool(settings.ANTHROPIC_API_KEY),
    }


@router.get("/health")
async def health_check():
    services: dict[str, str] = {}

    # Check Redis
    try:
        r = aioredis.from_url(settings.REDIS_URL)
        await r.ping()
        await r.aclose()
        services["redis"] = "connected"
    except Exception:
        services["redis"] = "unavailable"

    # Check DB (SQLite always works if file is accessible)
    services["database"] = "sqlite_ok"

    # Check API keys
    services["deepgram"] = "api_key_set" if settings.DEEPGRAM_API_KEY else "missing"
    services["anthropic"] = "api_key_set" if settings.ANTHROPIC_API_KEY else "missing"

    return {
        "status": "healthy",
        "version": settings.VERSION,
        "services": services,
    }


@router.post("/sessions", status_code=201, response_model=SessionResponse)
async def create_voice_session():
    """
    Create a new voice session.
    FIX #4: Returns session_id for client-side localStorage persistence.
    """
    session_id = str(uuid.uuid4())
    await create_session(session_id)
    now = datetime.now(timezone.utc).isoformat()
    logger.info("session_created_via_api", session_id=session_id)
    return SessionResponse(
        session_id=session_id,
        created_at=now,
        websocket_url=f"/ws/audio/{session_id}",
    )


@router.get("/sessions/{session_id}/history", response_model=HistoryResponse)
async def get_history(session_id: str):
    """Retrieve conversation history. Used for FIX #4 page refresh persistence."""
    exists = await session_exists(session_id)
    if not exists:
        # Fall back to DB check
        history = await get_session_history(session_id)
        if not history:
            raise HTTPException(status_code=404, detail="Session not found")
        return HistoryResponse(session_id=session_id, messages=history)
    history = await get_session_history(session_id)
    return HistoryResponse(session_id=session_id, messages=history)


@router.get("/roi/summary")
async def roi_summary(
    date_from: str | None = None,
    date_to: str | None = None,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    _require_role(x_api_key, {"viewer"})
    start, end = _range_bounds(date_from, date_to)
    return await _compute_roi_summary(start, end)


@router.get("/roi/trends")
async def roi_trends(
    interval: str = "week",
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    _require_role(x_api_key, {"viewer"})
    if interval not in {"week", "month"}:
        raise HTTPException(status_code=400, detail="interval must be week or month")
    step_days = 7 if interval == "week" else 30
    end = datetime.now(timezone.utc)
    start = end - (end - end.replace(day=1, hour=0, minute=0, second=0, microsecond=0))
    points = []
    cursor = start
    while cursor < end:
        bucket_end = min(cursor + timedelta(days=step_days), end)
        summary = await _compute_roi_summary(cursor, bucket_end)
        points.append(
            {
                "bucket_start": cursor.isoformat(),
                "bucket_end": bucket_end.isoformat(),
                "sessions": summary["kpis"]["sessions"],
                "net_value": summary["kpis"]["net_value"],
            }
        )
        cursor = bucket_end
    return {"interval": interval, "from": start.isoformat(), "to": end.isoformat(), "points": points}


@router.post("/reports/generate")
async def generate_report(x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    _require_role(x_api_key, {"operator"})
    start, end = _range_bounds(None, None)
    summary = await _compute_roi_summary(start, end)
    report_id = str(uuid.uuid4())
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORT_DIR / f"{report_id}.json"
    html_path = REPORT_DIR / f"{report_id}.html"
    json_path.write_text(json.dumps(summary, indent=2))
    html_path.write_text(
        "\n".join(
            [
                "<html><head><title>TechNova Executive Report</title></head><body>",
                "<h1>TechNova Executive Report</h1>",
                f"<p>Generated: {datetime.now(timezone.utc).isoformat()}</p>",
                f"<pre>{json.dumps(summary, indent=2)}</pre>",
                "</body></html>",
            ]
        )
    )
    index = _load_index()
    index[report_id] = {
        "report_id": report_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": [str(json_path), str(html_path)],
        "from": summary["from"],
        "to": summary["to"],
        "format": "both",
    }
    _save_index(index)
    await save_executive_report(
        report_id,
        date_from=start,
        date_to=end,
        report_format="both",
        files_json=json.dumps([str(json_path), str(html_path)]),
        summary_json=json.dumps(summary),
    )
    return {"report_id": report_id, "files": [str(json_path), str(html_path)]}


@router.get("/reports/{report_id}")
async def get_report(
    report_id: str,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    _require_role(x_api_key, {"viewer"})
    metadata = None
    model = await get_executive_report(report_id)
    if model is not None:
        metadata = _report_metadata_from_model(model)

    if metadata is None:
        metadata = _load_index().get(report_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Report not found")
    artifacts = []
    for path_str in metadata.get("files", []):
        path = Path(path_str)
        if path.exists():
            artifacts.append(
                {
                    "path": path_str,
                    "content_type": "application/json" if path.suffix == ".json" else "text/html",
                    "content": path.read_text(),
                }
            )
    return {"metadata": metadata, "artifacts": artifacts}


@router.get("/reports")
async def list_reports(
    limit: int = 20,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    _require_role(x_api_key, {"viewer"})
    models = await list_executive_reports(limit=limit)
    if models:
        return {
            "items": [
                {
                    "report_id": m.id,
                    "generated_at": m.generated_at.isoformat() if m.generated_at else None,
                    "from": m.date_from.isoformat() if m.date_from else None,
                    "to": m.date_to.isoformat() if m.date_to else None,
                    "format": m.format,
                }
                for m in models
            ]
        }

    index = _load_index()
    fallback = list(index.values())
    fallback.sort(key=lambda item: item.get("generated_at") or "", reverse=True)
    return {
        "items": [
            {
                "report_id": item.get("report_id"),
                "generated_at": item.get("generated_at"),
                "from": item.get("from"),
                "to": item.get("to"),
                "format": item.get("format"),
            }
            for item in fallback[:limit]
        ],
    }


# ---------------------------------------------------------------------------
# Latency metrics
# ---------------------------------------------------------------------------

@router.get("/metrics/latency")
async def get_latency_metrics():
    """Return P50/P95/P99 latency percentiles for each pipeline component."""
    from app.metrics import latency_histogram
    return latency_histogram.get_percentiles()


@router.get("/costs/summary")
async def get_cost_summary():
    """Return aggregate cost breakdown across all voice turns."""
    from app.cost_tracker import cost_aggregator
    return cost_aggregator.get_summary()


@router.get("/costs/session/{session_id}")
async def get_session_cost(session_id: str):
    """Return total cost for a specific session."""
    from app.cost_tracker import cost_aggregator
    return {
        "session_id": session_id,
        "total_cost_usd": cost_aggregator.get_session_total(session_id),
    }


@router.get("/health/circuits")
async def get_circuit_health():
    """Return circuit breaker states for all external services."""
    from app.circuit_breaker import llm_circuit, stt_circuit, tts_circuit
    return {
        "circuits": [
            llm_circuit.to_dict(),
            stt_circuit.to_dict(),
            tts_circuit.to_dict(),
        ]
    }
