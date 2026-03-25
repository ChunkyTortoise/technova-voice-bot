from __future__ import annotations
import asyncio
import json
import uuid as _uuid
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.config import settings
from app.ws_manager import manager
from app.audio_pipeline import AudioPipeline
from app.stt_client import DeepgramSTTClient
from app.tts_client import DeepgramTTSClient
from app.cost_tracker import compute_turn_cost, cost_aggregator
from app.llm_orchestrator import generate_response, TurnResult
from app.metrics import PipelineTimings, latency_histogram, timer
from app.mock_clients import MockLLMOrchestrator, MockTTSClient
from app.session_manager import session_exists
from app.utils.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter()

DEMO_MODE = not settings.DEEPGRAM_API_KEY or not settings.ANTHROPIC_API_KEY

if DEMO_MODE:
    _mock_llm = MockLLMOrchestrator()
    _mock_tts = MockTTSClient()


@router.websocket("/ws/audio/{session_id}")
async def audio_websocket(websocket: WebSocket, session_id: str):
    """
    Main voice pipeline WebSocket endpoint.
    FIX #8: Rate limit by IP (max MAX_CONCURRENT_WS_PER_IP per IP)
    FIX #18: Handle ping messages for keepalive
    """
    # Validate session_id is a well-formed UUID to prevent Redis key pollution
    try:
        _uuid.UUID(session_id)
    except ValueError:
        await websocket.close(code=1008, reason="Invalid session_id format")
        return

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
            if DEMO_MODE:
                audio = await _mock_tts.synthesize(sentence)
                await manager.send_audio(session_id, audio)
            else:
                tts = DeepgramTTSClient(on_audio_chunk=on_audio_chunk)
                await manager.send_event(session_id, {"type": "bot_start"})
                await tts.synthesize(sentence)

    # Track last PCM data for cost computation (audio duration)
    _last_pcm_data: list[bytes] = [b""]

    async def on_speech_end(pcm_data: bytes) -> None:
        """Called when VAD detects end of user utterance."""
        if not pcm_data:
            return
        _last_pcm_data[0] = pcm_data
        cancel_event.clear()
        if DEMO_MODE:
            await on_transcript_received("Demo user speech detected")
        else:
            stt = DeepgramSTTClient(on_transcript=on_transcript_received)
            await stt.connect()
            await stt.send_audio(pcm_data)
            await stt.disconnect()

    async def on_transcript_received(text: str) -> None:
        if not text.strip():
            return
        await manager.send_event(session_id, {"type": "transcript", "text": text})
        logger.info("pipeline_transcript", session_id=session_id, text=text[:80])

        timings = PipelineTimings(session_id=session_id)
        tts_chars = 0

        async def on_tts_sentence_tracked(sentence: str) -> None:
            nonlocal tts_chars
            tts_chars += len(sentence)
            await on_tts_sentence(sentence)

        try:
            if DEMO_MODE:
                response = await _mock_llm.generate_response(text, session_id)
                await manager.send_event(session_id, {"type": "bot_start"})
                tts_chars += len(response)
                await on_tts_sentence(response)
            else:
                async def on_tool_call(name: str, args: dict) -> None:
                    await manager.send_event(session_id, {
                        "type": "tool_call", "name": name, "args": args,
                    })

                async with timer() as e2e_timer:
                    turn_result = await generate_response(
                        session_id=session_id,
                        user_text=text,
                        on_sentence=on_tts_sentence_tracked,
                        cancel_event=cancel_event,
                        on_tool_call=on_tool_call,
                    )
                    timings.llm_ttfb_ms = turn_result.ttfb_ms
                    timings.llm_total_ms = turn_result.total_ms
                timings.e2e_ms = e2e_timer.elapsed_ms
                latency_histogram.record(timings)

            await manager.send_event(session_id, {"type": "bot_end"})

            # Compute cost and record
            if not DEMO_MODE:
                audio_sec = len(_last_pcm_data[0]) / (16000 * 2) if _last_pcm_data[0] else 0.0
                turn_cost = compute_turn_cost(
                    audio_duration_sec=audio_sec,
                    tokens_in=turn_result.tokens_in,
                    tokens_out=turn_result.tokens_out,
                    tts_chars=tts_chars,
                    model=turn_result.model_used,
                )
                cost_aggregator.record(session_id, turn_cost)
            else:
                turn_cost = None

            # Send latency + cost breakdown to client
            event_data = {"type": "latency", **timings.to_dict()}
            if turn_cost:
                event_data["cost_usd"] = round(turn_cost.total_cost, 6)
            await manager.send_event(session_id, event_data)
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
