from __future__ import annotations
import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.config import settings
from app.ws_manager import manager
from app.audio_pipeline import AudioPipeline
from app.stt_client import DeepgramSTTClient
from app.tts_client import DeepgramTTSClient
from app.llm_orchestrator import generate_response
from app.session_manager import session_exists
from app.utils.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.websocket("/ws/audio/{session_id}")
async def audio_websocket(websocket: WebSocket, session_id: str):
    """
    Main voice pipeline WebSocket endpoint.
    FIX #8: Rate limit by IP (max MAX_CONCURRENT_WS_PER_IP per IP)
    FIX #18: Handle ping messages for keepalive
    """
    # FIX #8: Check concurrent connections per IP
    client_ip = websocket.client.host if websocket.client else "unknown"
    current_count = manager.get_connection_count_for_ip(client_ip)
    if current_count >= settings.MAX_CONCURRENT_WS_PER_IP:
        logger.warning("ws_rate_limit", ip=client_ip, count=current_count)
        await websocket.close(code=1008, reason="Too many connections from this IP")
        return

    # Verify session exists
    if not await session_exists(session_id):
        await websocket.close(code=1008, reason="Invalid session_id")
        return

    await manager.connect(session_id, websocket)
    manager.register_ip(session_id, client_ip)

    cancel_event = asyncio.Event()

    async def on_audio_chunk(chunk: bytes) -> None:
        await manager.send_audio(session_id, chunk)

    async def on_tts_sentence(sentence: str) -> None:
        if not cancel_event.is_set():
            tts = DeepgramTTSClient(on_audio_chunk=on_audio_chunk)
            await manager.send_event(session_id, {"type": "bot_start"})
            await tts.synthesize(sentence)

    async def on_speech_end(pcm_data: bytes) -> None:
        """Called when VAD detects end of user utterance."""
        cancel_event.clear()
        stt = DeepgramSTTClient(on_transcript=on_transcript_received)
        await stt.connect()
        await stt.send_audio(pcm_data)
        await stt.disconnect()

    async def on_transcript_received(text: str) -> None:
        if not text.strip():
            return
        await manager.send_event(session_id, {"type": "transcript", "text": text})
        logger.info("pipeline_transcript", session_id=session_id, text=text[:80])
        try:
            await generate_response(
                session_id=session_id,
                user_text=text,
                on_sentence=on_tts_sentence,
                cancel_event=cancel_event,
            )
            await manager.send_event(session_id, {"type": "bot_end"})
        except Exception as e:
            logger.error("pipeline_error", session_id=session_id, error=str(e))
            await manager.send_event(session_id, {"type": "error", "message": "Processing error"})

    pipeline = AudioPipeline(session_id=session_id, on_speech_end=on_speech_end)
    await pipeline.start()

    try:
        while True:
            try:
                # FIX #18: Handle both binary audio and JSON control messages
                data = await websocket.receive()

                if "bytes" in data and data["bytes"]:
                    # Binary audio chunk
                    cancel_event.clear()
                    await pipeline.feed_chunk(data["bytes"])

                elif "text" in data and data["text"]:
                    # JSON control message
                    try:
                        msg = json.loads(data["text"])
                        if msg.get("type") == "ping":
                            # FIX #18: Respond to keepalive pings
                            await manager.send_event(session_id, {"type": "pong"})
                        elif msg.get("type") == "interrupt":
                            # Barge-in: cancel current bot response
                            cancel_event.set()
                            logger.info("barge_in", session_id=session_id)
                    except json.JSONDecodeError:
                        pass

            except WebSocketDisconnect:
                break
    finally:
        await pipeline.stop()
        await manager.disconnect(session_id)
        logger.info("ws_session_cleaned_up", session_id=session_id)
