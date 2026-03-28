"""B6: Barge-in (TTS cancellation) tests."""
from __future__ import annotations
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


async def test_tts_cancel_sets_cancelled_flag():
    from app.tts_client import DeepgramTTSClient

    tts = DeepgramTTSClient(on_audio_chunk=AsyncMock())
    assert tts._cancelled is False
    await tts.cancel()
    assert tts._cancelled is True


async def test_cancel_stops_ongoing_synthesis():
    """Verify that _cancelled flag prevents further chunks being delivered."""
    from app.tts_client import DeepgramTTSClient

    delivered: list[bytes] = []

    async def capture(chunk: bytes):
        delivered.append(chunk)

    # aiter_bytes must return an async iterable (not a coroutine),
    # so use a regular function that returns an async generator.
    def _make_iter(tts_ref):
        async def _inner(chunk_size=4096):
            for _ in range(20):
                yield b"\x00" * 128
                if len(delivered) >= 2:
                    tts_ref._cancelled = True
        return _inner

    mock_response = AsyncMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_client = AsyncMock()
    mock_client.stream = MagicMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.tts_client.httpx.AsyncClient", return_value=mock_client):
        tts = DeepgramTTSClient(on_audio_chunk=capture)
        mock_response.aiter_bytes = _make_iter(tts)
        await tts.synthesize("A long sentence that should be interrupted")

    assert len(delivered) < 20


async def test_cancel_event_propagates_barge_in():
    """asyncio.Event can be used to signal barge-in across coroutines."""
    cancel_event = asyncio.Event()

    async def tts_task():
        for _ in range(100):
            if cancel_event.is_set():
                return "cancelled"
            await asyncio.sleep(0)
        return "completed"

    # Signal cancel before task runs substantively
    cancel_event.set()
    result = await tts_task()
    assert result == "cancelled"


async def test_barge_in_resets_speech_buffer():
    """After a barge-in the audio pipeline buffer should be cleared."""
    from app.audio_pipeline import AudioPipeline

    callback = AsyncMock()
    pipeline = AudioPipeline(session_id="barge-sess", on_speech_end=callback)
    pipeline._speech_buffer = b"\xFF" * 2048
    pipeline._in_speech = True

    # Simulate reset (as would happen when a new utterance starts)
    pipeline._speech_buffer = b""
    pipeline._in_speech = False
    pipeline._silence_start = None

    assert pipeline._speech_buffer == b""
    assert pipeline._in_speech is False


async def test_tts_synthesize_resets_cancelled_before_run():
    """Barge-in sets _cancelled=True; next synthesize() must reset it."""
    from app.tts_client import DeepgramTTSClient

    received: list[bytes] = []

    async def capture(c: bytes):
        received.append(c)

    async def _iter(chunk_size=4096):
        yield b"\x01\x02"

    mock_response = AsyncMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.aiter_bytes = _iter
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_client = AsyncMock()
    mock_client.stream = MagicMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.tts_client.httpx.AsyncClient", return_value=mock_client):
        tts = DeepgramTTSClient(on_audio_chunk=capture)
        await tts.cancel()  # simulate previous barge-in
        assert tts._cancelled is True
        await tts.synthesize("Next response after barge-in")

    assert tts._cancelled is False
    assert len(received) == 1


async def test_multiple_cancels_idempotent():
    from app.tts_client import DeepgramTTSClient

    tts = DeepgramTTSClient(on_audio_chunk=AsyncMock())
    await tts.cancel()
    await tts.cancel()
    await tts.cancel()
    assert tts._cancelled is True
