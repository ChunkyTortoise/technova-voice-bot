"""B4: DeepgramTTSClient unit tests — mocks httpx.AsyncClient."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_streaming_response(chunks: list[bytes]) -> AsyncMock:
    """Build a mock for the inner stream context manager."""
    async def _iter_bytes(chunk_size: int = 4096):
        for chunk in chunks:
            yield chunk

    response = AsyncMock()
    response.raise_for_status = MagicMock()
    response.aiter_bytes = _iter_bytes
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)
    return response


def _make_http_client(response: AsyncMock) -> AsyncMock:
    client = AsyncMock()
    client.stream = MagicMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


async def test_init_not_cancelled():
    from app.tts_client import DeepgramTTSClient

    callback = AsyncMock()
    tts = DeepgramTTSClient(on_audio_chunk=callback)
    assert tts._cancelled is False
    assert tts.on_audio_chunk is callback


async def test_synthesize_empty_text_is_noop():
    from app.tts_client import DeepgramTTSClient

    callback = AsyncMock()
    tts = DeepgramTTSClient(on_audio_chunk=callback)
    await tts.synthesize("   ")
    callback.assert_not_called()


async def test_synthesize_streams_chunks_to_callback():
    from app.tts_client import DeepgramTTSClient

    received: list[bytes] = []

    async def capture(chunk: bytes):
        received.append(chunk)

    chunks = [b"\x00\x01", b"\x02\x03"]
    response = _make_streaming_response(chunks)
    http_client = _make_http_client(response)

    with patch("app.tts_client.httpx.AsyncClient", return_value=http_client):
        tts = DeepgramTTSClient(on_audio_chunk=capture)
        await tts.synthesize("Hello world")

    assert received == chunks


async def test_synthesize_stops_on_cancel():
    from app.tts_client import DeepgramTTSClient

    received: list[bytes] = []
    call_count = 0

    async def capture(chunk: bytes):
        nonlocal call_count
        call_count += 1
        received.append(chunk)

    # Many chunks — but we cancel after receiving the first
    chunks = [b"\x00" * 4096] * 10
    response = _make_streaming_response(chunks)
    original_iter = response.aiter_bytes

    async def iter_and_cancel(chunk_size: int = 4096):
        async for chunk in original_iter(chunk_size):
            yield chunk
            # Cancel after first chunk delivered via callback
            if call_count >= 1:
                tts._cancelled = True

    response.aiter_bytes = iter_and_cancel
    http_client = _make_http_client(response)

    with patch("app.tts_client.httpx.AsyncClient", return_value=http_client):
        tts = DeepgramTTSClient(on_audio_chunk=capture)
        await tts.synthesize("Hello world")

    assert call_count < len(chunks)


async def test_cancel_sets_flag():
    from app.tts_client import DeepgramTTSClient

    tts = DeepgramTTSClient(on_audio_chunk=AsyncMock())
    assert tts._cancelled is False
    await tts.cancel()
    assert tts._cancelled is True


async def test_synthesize_resets_cancel_flag():
    """Each synthesize() call resets _cancelled so it can run again."""
    from app.tts_client import DeepgramTTSClient

    callback = AsyncMock()
    tts = DeepgramTTSClient(on_audio_chunk=callback)
    tts._cancelled = True  # simulate previous cancellation

    response = _make_streaming_response([b"\x00\x01"])
    http_client = _make_http_client(response)

    with patch("app.tts_client.httpx.AsyncClient", return_value=http_client):
        await tts.synthesize("new text")

    assert tts._cancelled is False
    callback.assert_called_once()


async def test_synthesize_propagates_http_error():
    from app.tts_client import DeepgramTTSClient
    import httpx

    response = AsyncMock()
    response.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError(
        "403", request=MagicMock(), response=MagicMock()
    ))
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)
    http_client = _make_http_client(response)

    with patch("app.tts_client.httpx.AsyncClient", return_value=http_client):
        tts = DeepgramTTSClient(on_audio_chunk=AsyncMock())
        with pytest.raises(httpx.HTTPStatusError):
            await tts.synthesize("some text")


async def test_synthesize_skips_empty_chunks():
    from app.tts_client import DeepgramTTSClient

    received: list[bytes] = []

    async def capture(chunk: bytes):
        received.append(chunk)

    chunks = [b"", b"\x01\x02", b"", b"\x03\x04"]
    response = _make_streaming_response(chunks)
    http_client = _make_http_client(response)

    with patch("app.tts_client.httpx.AsyncClient", return_value=http_client):
        tts = DeepgramTTSClient(on_audio_chunk=capture)
        await tts.synthesize("Hello")

    # Only non-empty chunks are forwarded
    assert received == [b"\x01\x02", b"\x03\x04"]
