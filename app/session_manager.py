from __future__ import annotations
import json
import asyncio
from datetime import datetime, timezone
import redis.asyncio as aioredis
from app.config import settings
from app.database import save_message, create_session as db_create_session
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

_redis_client: aioredis.Redis | None = None
# FIX #9: Per-session asyncio locks for single-process deployments
_session_locks: dict[str, asyncio.Lock] = {}
_locks_mutex = asyncio.Lock()


async def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


async def close_redis() -> None:
    global _redis_client
    if _redis_client:
        await _redis_client.aclose()
        _redis_client = None


async def get_session_lock(session_id: str) -> asyncio.Lock:
    """Get or create an asyncio.Lock for the session (single-process concurrency)."""
    async with _locks_mutex:
        if session_id not in _session_locks:
            _session_locks[session_id] = asyncio.Lock()
        return _session_locks[session_id]


async def create_session(session_id: str) -> dict:
    r = await get_redis()
    session_data = {
        "session_id": session_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "message_count": 0,
    }
    await r.setex(
        f"session:{session_id}:meta",
        settings.SESSION_TTL_SECONDS,
        json.dumps(session_data),
    )
    await r.delete(f"session:{session_id}:messages")
    # Persist to DB
    await db_create_session(session_id)
    logger.info("session_created", session_id=session_id)
    return session_data


async def session_exists(session_id: str) -> bool:
    r = await get_redis()
    return bool(await r.exists(f"session:{session_id}:meta"))


async def get_conversation(session_id: str) -> list[dict]:
    r = await get_redis()
    raw = await r.lrange(f"session:{session_id}:messages", 0, -1)  # type: ignore[misc]
    return [json.loads(m) for m in raw]


async def append_message(session_id: str, role: str, content: str) -> None:
    r = await get_redis()
    message = {
        "role": role,
        "content": content,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    key = f"session:{session_id}:messages"
    await r.rpush(key, json.dumps(message))  # type: ignore[misc]
    await r.expire(key, settings.SESSION_TTL_SECONDS)

    # Always persist to DB (Redis is the fast cache; SQLite is the durable store)
    await save_message(session_id, role, content)


# FIX #9: Redis distributed lock (for multi-process; asyncio.Lock used in routes)
async def acquire_redis_lock(session_id: str) -> bool:
    r = await get_redis()
    lock_key = f"session:{session_id}:lock"
    result = await r.set(lock_key, "1", nx=True, ex=settings.LOCK_TTL_SECONDS)
    return bool(result)


async def release_redis_lock(session_id: str) -> None:
    r = await get_redis()
    await r.delete(f"session:{session_id}:lock")


async def refresh_redis_lock(session_id: str) -> None:
    """Heartbeat renewal for long-running LLM responses."""
    r = await get_redis()
    await r.expire(f"session:{session_id}:lock", settings.LOCK_TTL_SECONDS)
