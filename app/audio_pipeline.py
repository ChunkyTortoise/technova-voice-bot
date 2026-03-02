from __future__ import annotations
import asyncio
import subprocess
import time
from typing import Callable, Awaitable
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

VAD_THRESHOLD = 0.5
ENDPOINTING_MS = 700  # 700ms silence = end of utterance
FRAME_SAMPLES = 512   # 32ms at 16kHz

try:
    import numpy as np
    import onnxruntime as ort
    import urllib.request
    import os

    ONNX_MODEL_PATH = os.environ.get("SILERO_VAD_PATH", "/app/data/silero_vad.onnx")
    _ort_session: ort.InferenceSession | None = None

    def _ensure_model() -> ort.InferenceSession:
        global _ort_session
        if _ort_session is not None:
            return _ort_session
        if not os.path.exists(ONNX_MODEL_PATH):
            os.makedirs(os.path.dirname(ONNX_MODEL_PATH), exist_ok=True)
            url = "https://raw.githubusercontent.com/snakers4/silero-vad/master/src/silero_vad/data/silero_vad.onnx"
            logger.info("downloading_silero_vad_onnx", url=url, path=ONNX_MODEL_PATH)
            urllib.request.urlretrieve(url, ONNX_MODEL_PATH)
        _ort_session = ort.InferenceSession(ONNX_MODEL_PATH)
        return _ort_session

    VAD_AVAILABLE = True
except ImportError:
    VAD_AVAILABLE = False
    logger.warning("onnxruntime_not_available", detail="Using Deepgram built-in VAD instead")


def _vad_probability(pcm_bytes: bytes) -> float:
    """Return speech probability for a 512-sample PCM16 frame."""
    if not VAD_AVAILABLE:
        return 1.0  # Pass-through if VAD not available
    import numpy as np
    session = _ensure_model()
    audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    if len(audio) < FRAME_SAMPLES:
        audio = np.pad(audio, (0, FRAME_SAMPLES - len(audio)))
    audio = audio[:FRAME_SAMPLES].reshape(1, -1)
    h = np.zeros((2, 1, 64), dtype=np.float32)
    c = np.zeros((2, 1, 64), dtype=np.float32)
    inputs = {"input": audio, "h": h, "c": c, "sr": np.array(16000, dtype=np.int64)}
    outputs = session.run(None, inputs)
    return float(outputs[0])


class AudioPipeline:
    """
    FIX #1: Use OGG for reliable streaming (not WebM which requires seeking).
    FIX #2: ONNX Silero VAD instead of PyTorch.

    Receives OGG/Opus audio chunks from browser, transcodes to PCM16 via FFmpeg,
    runs Silero VAD to detect speech/silence, and calls on_speech_end when utterance ends.
    """

    def __init__(
        self,
        session_id: str,
        on_speech_end: Callable[[bytes], Awaitable[None]],
    ) -> None:
        self.session_id = session_id
        self.on_speech_end = on_speech_end
        self._ffmpeg: subprocess.Popen | None = None
        self._pcm_buffer: bytes = b""
        self._speech_buffer: bytes = b""
        self._in_speech = False
        self._silence_start: float | None = None
        self._read_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start FFmpeg subprocess. FIX #1: -f ogg for streamable OGG container."""
        cmd = [
            "ffmpeg",
            "-loglevel", "error",
            "-f", "ogg",           # FIX #1: OGG is streamable (not WebM)
            "-i", "pipe:0",
            "-f", "s16le",
            "-ar", "16000",
            "-ac", "1",
            "pipe:1",
        ]
        self._ffmpeg = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self._read_task = asyncio.create_task(self._read_pcm())
        logger.info("audio_pipeline_started", session_id=self.session_id)

    async def feed_chunk(self, chunk: bytes) -> None:
        """Feed OGG/Opus audio chunk from browser into FFmpeg."""
        if self._ffmpeg and self._ffmpeg.stdin:
            try:
                self._ffmpeg.stdin.write(chunk)
                self._ffmpeg.stdin.flush()
            except BrokenPipeError:
                logger.warning("ffmpeg_pipe_broken", session_id=self.session_id)

    async def _read_pcm(self) -> None:
        """Read PCM16 output from FFmpeg and run VAD."""
        frame_bytes = FRAME_SAMPLES * 2  # 16-bit samples
        loop = asyncio.get_event_loop()

        while self._ffmpeg and self._ffmpeg.poll() is None:
            if not self._ffmpeg.stdout:
                break
            try:
                chunk = await loop.run_in_executor(
                    None, self._ffmpeg.stdout.read, frame_bytes
                )
            except Exception:
                break
            if not chunk:
                break
            await self._process_frame(chunk)

    async def _process_frame(self, pcm_chunk: bytes) -> None:
        """Run VAD on a PCM frame and manage speech/silence state."""
        prob = _vad_probability(pcm_chunk)

        if prob >= VAD_THRESHOLD:
            self._in_speech = True
            self._silence_start = None
            self._speech_buffer += pcm_chunk
        elif self._in_speech:
            self._speech_buffer += pcm_chunk
            if self._silence_start is None:
                self._silence_start = time.monotonic()
            elif (time.monotonic() - self._silence_start) * 1000 >= ENDPOINTING_MS:
                # Utterance complete
                speech_data = self._speech_buffer
                self._speech_buffer = b""
                self._in_speech = False
                self._silence_start = None
                logger.info("utterance_end", session_id=self.session_id, bytes=len(speech_data))
                await self.on_speech_end(speech_data)

    async def stop(self) -> None:
        """Cleanup FFmpeg process."""
        if self._read_task:
            self._read_task.cancel()
        if self._ffmpeg:
            try:
                if self._ffmpeg.stdin:
                    self._ffmpeg.stdin.close()
                self._ffmpeg.terminate()
                self._ffmpeg.wait(timeout=2)
            except Exception:
                self._ffmpeg.kill()
        logger.info("audio_pipeline_stopped", session_id=self.session_id)
