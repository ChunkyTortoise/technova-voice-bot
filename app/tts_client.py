from __future__ import annotations
from typing import Callable, Awaitable
import httpx
from app.config import settings
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

TTS_API_URL = "https://api.deepgram.com/v1/speak"


class DeepgramTTSClient:
    """
    Deepgram Aura-2 TTS via REST streaming API.
    Returns PCM16 audio chunks for immediate playback.
    """

    def __init__(self, on_audio_chunk: Callable[[bytes], Awaitable[None]]) -> None:
        self.on_audio_chunk = on_audio_chunk
        self._cancelled = False

    async def synthesize(self, text: str) -> None:
        """Synthesize text and stream PCM16 chunks to callback."""
        if not text.strip():
            return
        self._cancelled = False
        params = {
            "model": "aura-2-thalia-en",
            "encoding": "linear16",
            "sample_rate": "24000",
            "container": "none",
        }
        headers = {
            "Authorization": f"Token {settings.DEEPGRAM_API_KEY}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            async with client.stream(
                "POST",
                TTS_API_URL,
                headers=headers,
                params=params,
                json={"text": text},
            ) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes(chunk_size=4096):
                    if self._cancelled:
                        logger.debug("tts_cancelled", text_prefix=text[:40])
                        break
                    if chunk:
                        await self.on_audio_chunk(chunk)
        logger.debug("tts_complete", chars=len(text))

    async def cancel(self) -> None:
        """Cancel in-progress synthesis (barge-in)."""
        self._cancelled = True
