"""Mock clients for demo mode (no API keys required)."""
from __future__ import annotations

import asyncio
import logging
import random
from typing import AsyncIterator

logger = logging.getLogger(__name__)

DEMO_RESPONSES = [
    "Hello! I'm TechNova's AI assistant running in demo mode. How can I help you today?",
    "That's a great question! In a production deployment, I would process your audio through Deepgram for speech recognition and respond using Claude AI. Right now I'm showing you the demo experience.",
    "I can handle real-time voice conversations, detect speech activity, and stream responses back instantly. The full pipeline uses FFmpeg for audio processing and Silero VAD for voice activity detection.",
    "This demo showcases the real-time WebSocket infrastructure. In production, your voice goes through: FFmpeg conversion, VAD detection, Deepgram STT, Claude LLM, and Deepgram TTS — all in under 2 seconds.",
    "Want to see the full system? Deploy with a Deepgram API key and Anthropic API key and experience the complete voice AI pipeline.",
]

DEMO_TRANSCRIPT_RESPONSES = [
    "Demo transcript: User spoke for approximately 2 seconds.",
    "Demo transcript: Voice activity detected and processed.",
    "Demo transcript: Audio stream received and analyzed.",
]


class MockSTTClient:
    """Mock Deepgram STT client for demo mode."""

    def __init__(self) -> None:
        logger.info("MockSTTClient initialized (demo mode)")

    async def transcribe_stream(
        self, audio_chunks: AsyncIterator[bytes]
    ) -> AsyncIterator[str]:
        """Consume audio chunks and yield fake transcripts."""
        async def _generate() -> AsyncIterator[str]:
            async for _ in audio_chunks:
                pass  # consume chunks
            await asyncio.sleep(0.5)
            yield random.choice(DEMO_TRANSCRIPT_RESPONSES)

        return _generate()

    async def close(self) -> None:
        pass


class MockTTSClient:
    """Mock Deepgram TTS client for demo mode."""

    def __init__(self) -> None:
        logger.info("MockTTSClient initialized (demo mode)")

    async def synthesize(self, text: str) -> bytes:
        """Return silent audio bytes (mock WAV header)."""
        await asyncio.sleep(0.1)
        # Minimal valid WAV header for 0.5s silence at 16kHz mono
        return b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"

    async def close(self) -> None:
        pass


class MockLLMOrchestrator:
    """Mock LLM orchestrator for demo mode."""

    def __init__(self) -> None:
        self._call_count = 0
        logger.info("MockLLMOrchestrator initialized (demo mode)")

    async def generate_response(
        self,
        transcript: str,
        session_id: str | None = None,
        **kwargs: object,
    ) -> str:
        """Return a canned demo response."""
        self._call_count += 1
        idx = (self._call_count - 1) % len(DEMO_RESPONSES)
        await asyncio.sleep(0.2)
        return DEMO_RESPONSES[idx]

    async def generate_response_stream(
        self,
        transcript: str,
        session_id: str | None = None,
        **kwargs: object,
    ) -> AsyncIterator[str]:
        """Stream a canned demo response token by token."""
        response = await self.generate_response(transcript, session_id)
        async def _stream() -> AsyncIterator[str]:
            for word in response.split():
                yield word + " "
                await asyncio.sleep(0.05)
        return _stream()

    async def close(self) -> None:
        pass
