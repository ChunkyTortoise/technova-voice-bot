"""B5: AudioPipeline VAD, buffering, FFmpeg spawning, and cleanup tests."""
from __future__ import annotations
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pipeline(on_speech_end: AsyncMock | None = None):
    from app.audio_pipeline import AudioPipeline

    callback = on_speech_end or AsyncMock()
    pipeline = AudioPipeline(session_id="test-sess", on_speech_end=callback)
    return pipeline, callback


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

def test_pipeline_initial_state():
    pipeline, _ = _make_pipeline()
    assert pipeline.session_id == "test-sess"
    assert pipeline._in_speech is False
    assert pipeline._speech_buffer == b""
    assert pipeline._ffmpeg is None
    assert pipeline._silence_start is None


# ---------------------------------------------------------------------------
# start() spawns FFmpeg
# ---------------------------------------------------------------------------

async def test_start_spawns_ffmpeg():
    pipeline, _ = _make_pipeline()
    mock_proc = MagicMock()
    mock_proc.stdin = MagicMock()
    mock_proc.stdout = MagicMock()
    mock_proc.poll = MagicMock(return_value=0)  # already exited → _read_pcm returns quickly

    with patch("app.audio_pipeline.subprocess.Popen", return_value=mock_proc) as mock_popen:
        await pipeline.start()
        mock_popen.assert_called_once()
        call_args = mock_popen.call_args[0][0]
        assert "ffmpeg" in call_args
        assert "ogg" in call_args


# ---------------------------------------------------------------------------
# feed_chunk
# ---------------------------------------------------------------------------

async def test_feed_chunk_writes_to_stdin():
    pipeline, _ = _make_pipeline()
    mock_stdin = MagicMock()
    mock_proc = MagicMock()
    mock_proc.stdin = mock_stdin
    mock_proc.poll = MagicMock(return_value=0)
    mock_proc.stdout = MagicMock()
    pipeline._ffmpeg = mock_proc

    await pipeline.feed_chunk(b"\xDE\xAD\xBE\xEF")
    mock_stdin.write.assert_called_once_with(b"\xDE\xAD\xBE\xEF")
    mock_stdin.flush.assert_called_once()


async def test_feed_chunk_noop_when_no_ffmpeg():
    pipeline, _ = _make_pipeline()
    # _ffmpeg is None — must not raise
    await pipeline.feed_chunk(b"\x00")


async def test_feed_chunk_swallows_broken_pipe():
    pipeline, _ = _make_pipeline()
    mock_stdin = MagicMock()
    mock_stdin.write = MagicMock(side_effect=BrokenPipeError)
    mock_proc = MagicMock()
    mock_proc.stdin = mock_stdin
    pipeline._ffmpeg = mock_proc
    # Must not raise
    await pipeline.feed_chunk(b"\x00")


# ---------------------------------------------------------------------------
# _process_frame VAD logic
# ---------------------------------------------------------------------------

async def test_process_frame_starts_speech_on_high_prob():
    pipeline, _ = _make_pipeline()
    with patch("app.audio_pipeline._vad_probability", return_value=0.9):
        await pipeline._process_frame(b"\x00" * 1024)
    assert pipeline._in_speech is True
    assert len(pipeline._speech_buffer) == 1024


async def test_process_frame_no_speech_on_low_prob():
    pipeline, _ = _make_pipeline()
    with patch("app.audio_pipeline._vad_probability", return_value=0.1):
        await pipeline._process_frame(b"\x00" * 1024)
    assert pipeline._in_speech is False
    assert pipeline._speech_buffer == b""


async def test_process_frame_buffers_silence_after_speech():
    pipeline, _ = _make_pipeline()
    # First frame: speech detected
    with patch("app.audio_pipeline._vad_probability", return_value=0.9):
        await pipeline._process_frame(b"\x01" * 512)
    # Second frame: silence while in speech
    with patch("app.audio_pipeline._vad_probability", return_value=0.1):
        await pipeline._process_frame(b"\x02" * 512)
    assert pipeline._in_speech is True  # still in speech (timeout not reached)
    assert pipeline._silence_start is not None


async def test_process_frame_triggers_callback_after_endpointing():
    pipeline, callback = _make_pipeline()
    frame = b"\x00" * 512

    # Speak
    with patch("app.audio_pipeline._vad_probability", return_value=0.9):
        await pipeline._process_frame(frame)

    # Silence with monotonic time moving past ENDPOINTING_MS (700ms)
    time_vals = iter([0.0, 1.0])  # first call sets silence_start, second is > 700ms later
    with patch("app.audio_pipeline._vad_probability", return_value=0.1), \
         patch("app.audio_pipeline.time.monotonic", side_effect=time_vals):
        await pipeline._process_frame(frame)  # sets silence_start = 0.0
        with patch("app.audio_pipeline.time.monotonic", return_value=1.0):
            await pipeline._process_frame(frame)  # elapsed = 1000ms > 700ms

    callback.assert_called_once()
    args = callback.call_args[0]
    assert isinstance(args[0], bytes)
    # After callback: buffer reset
    assert pipeline._speech_buffer == b""
    assert pipeline._in_speech is False


async def test_process_frame_resets_state_after_utterance():
    pipeline, callback = _make_pipeline()
    frame = b"\xFF" * 512

    with patch("app.audio_pipeline._vad_probability", return_value=0.9):
        await pipeline._process_frame(frame)

    with patch("app.audio_pipeline._vad_probability", return_value=0.1), \
         patch("app.audio_pipeline.time.monotonic", side_effect=[0.0, 0.0]):
        await pipeline._process_frame(frame)

    with patch("app.audio_pipeline._vad_probability", return_value=0.1), \
         patch("app.audio_pipeline.time.monotonic", return_value=1.0):
        await pipeline._process_frame(frame)

    assert pipeline._in_speech is False
    assert pipeline._silence_start is None
    assert pipeline._speech_buffer == b""


# ---------------------------------------------------------------------------
# stop() cleanup
# ---------------------------------------------------------------------------

async def test_stop_terminates_ffmpeg():
    pipeline, _ = _make_pipeline()
    mock_proc = MagicMock()
    mock_proc.stdin = MagicMock()
    mock_proc.terminate = MagicMock()
    mock_proc.wait = MagicMock(return_value=0)
    mock_proc.kill = MagicMock()
    pipeline._ffmpeg = mock_proc
    pipeline._read_task = None

    await pipeline.stop()
    mock_proc.terminate.assert_called_once()


async def test_stop_cancels_read_task():
    pipeline, _ = _make_pipeline()

    async def long_running():
        await asyncio.sleep(100)

    task = asyncio.create_task(long_running())
    pipeline._read_task = task
    mock_proc = MagicMock()
    mock_proc.stdin = MagicMock()
    mock_proc.terminate = MagicMock()
    mock_proc.wait = MagicMock(return_value=0)
    pipeline._ffmpeg = mock_proc

    await pipeline.stop()
    assert task.cancelled()


async def test_stop_noop_when_not_started():
    pipeline, _ = _make_pipeline()
    # Must not raise
    await pipeline.stop()
