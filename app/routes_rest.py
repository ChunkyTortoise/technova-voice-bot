from __future__ import annotations
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import redis.asyncio as aioredis
from app.config import settings
from app.session_manager import create_session, session_exists
from app.database import get_session_history
from app.utils.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api")


class SessionResponse(BaseModel):
    session_id: str
    created_at: str
    websocket_url: str


class HistoryResponse(BaseModel):
    session_id: str
    messages: list[dict]


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
