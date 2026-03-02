from __future__ import annotations
from typing import Callable, Awaitable
from app.config import settings
from app.utils.logging_config import get_logger

logger = get_logger(__name__)


class DeepgramSTTClient:
    """
    Deepgram Nova-3 real-time STT via WebSocket.
    Deepgram SDK imports are deferred to connect() to avoid module-level failures
    when the SDK version changes between v3 and v4+.
    Requires deepgram-sdk>=3.7.0,<4.0.0 for LiveTranscriptionEvents + LiveOptions API.
    """

    def __init__(self, on_transcript: Callable[[str], Awaitable[None]]) -> None:
        self.on_transcript = on_transcript
        self._connection = None
        self._connected = False

    async def connect(self) -> None:
        # Deferred import — isolates SDK version dependency from module load
        from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions  # type: ignore[attr-defined]  # noqa: PLC0415

        options = LiveOptions(
            model="nova-3",
            language="en-US",
            encoding="linear16",
            sample_rate=16000,
            channels=1,
            punctuate=True,
            smart_format=True,
            interim_results=True,
            utterance_end_ms="1000",
            endpointing=700,
            vad_events=True,
        )
        client = DeepgramClient(settings.DEEPGRAM_API_KEY)
        self._connection = client.listen.asyncwebsocket.v("1")
        on_transcript = self.on_transcript

        async def on_message(self_inner, result, **kwargs):  # noqa: ANN001
            try:
                transcript = result.channel.alternatives[0].transcript
                if transcript and result.is_final:
                    logger.info("stt_transcript", text=transcript[:80])
                    await on_transcript(transcript)
            except (AttributeError, IndexError):
                pass

        self._connection.on(LiveTranscriptionEvents.Transcript, on_message)
        await self._connection.start(options)
        self._connected = True
        logger.info("stt_connected")

    async def send_audio(self, pcm_chunk: bytes) -> None:
        if self._connection and self._connected:
            await self._connection.send(pcm_chunk)

    async def disconnect(self) -> None:
        if self._connection:
            try:
                await self._connection.finish()
            except Exception:
                pass
            self._connected = False
            logger.info("stt_disconnected")
