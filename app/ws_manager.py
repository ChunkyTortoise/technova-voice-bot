from __future__ import annotations
import json
from collections import defaultdict
from fastapi import WebSocket
from app.utils.logging_config import get_logger

logger = get_logger(__name__)


class WebSocketManager:
    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}
        self._session_ip: dict[str, str] = {}  # session_id -> IP
        self._ip_sessions: dict[str, set[str]] = defaultdict(set)  # IP -> session_ids

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[session_id] = websocket
        logger.info("ws_connected", session_id=session_id)

    def register_ip(self, session_id: str, ip: str) -> None:
        self._session_ip[session_id] = ip
        self._ip_sessions[ip].add(session_id)

    def get_connection_count_for_ip(self, ip: str) -> int:
        return len(self._ip_sessions.get(ip, set()))

    async def disconnect(self, session_id: str) -> None:
        self._connections.pop(session_id, None)
        ip = self._session_ip.pop(session_id, None)
        if ip:
            self._ip_sessions[ip].discard(session_id)
        logger.info("ws_disconnected", session_id=session_id)

    async def send_audio(self, session_id: str, chunk: bytes) -> None:
        ws = self._connections.get(session_id)
        if ws:
            try:
                await ws.send_bytes(chunk)
            except Exception as e:
                logger.warning("ws_send_audio_error", session_id=session_id, error=str(e))

    async def send_event(self, session_id: str, event: dict) -> None:
        ws = self._connections.get(session_id)
        if ws:
            try:
                await ws.send_text(json.dumps(event))
            except Exception as e:
                logger.warning("ws_send_event_error", session_id=session_id, error=str(e))

    def is_connected(self, session_id: str) -> bool:
        return session_id in self._connections


manager = WebSocketManager()
