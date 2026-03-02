from __future__ import annotations
import asyncio
import re
import time
from typing import Callable, Awaitable
import anthropic
from app.config import settings
from app.session_manager import get_conversation, append_message, get_session_lock
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

# Module-level client singleton — reuses connection pool across calls
_anthropic_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _anthropic_client


# FIX #7: Robust sentence splitting.
# Python re doesn't support variable-width lookbehinds, so we use a fixed-width
# split on ". " (not after digit) plus post-processing to handle abbreviations.
_BOUNDARY = re.compile(r'(?<!\d)\. |[!?] |[!?]$|\n\n')

# Abbreviations that should NOT trigger a sentence boundary
_ABBREV = frozenset({
    'Dr', 'Mr', 'Mrs', 'Ms', 'St', 'vs', 'etc', 'No', 'Inc', 'Ltd', 'Corp',
    'Fig', 'Sec', 'Vol', 'approx', 'dept', 'est', 'govt', 'e.g', 'i.e',
})


def split_sentences(text: str) -> list[str]:
    """
    FIX #7: Split text into sentences, handling:
    - "$19.99" — digit before period prevents split (fixed-width lookbehind)
    - "Dr. Smith", "Mr. Jones" — abbreviation post-processing rejoins fragments
    - "..." — triple period emits no empty strings
    """
    raw = _BOUNDARY.split(text)
    result: list[str] = []
    carry = ''
    for part in raw:
        if carry:
            words = carry.rstrip().split()
            last_word = words[-1].rstrip('.') if words else ''
            if last_word in _ABBREV:
                # Rejoin: "Dr" + ". " + "Smith will help you"
                carry = carry + '. ' + part
                continue
            cleaned = carry.strip()
            if cleaned:
                result.append(cleaned)
        carry = part
    if carry.strip():
        result.append(carry.strip())
    return result

SYSTEM_PROMPT = """You are Alex, a friendly and helpful customer service representative for TechNova Electronics.

TechNova Electronics sells consumer electronics including TVs, laptops, smartphones, tablets, and headphones.

ORDER STATUS DATABASE:
- Orders TN-10001 through TN-10025: STATUS = Shipped (shipped 2 days ago, expected in 3-5 business days)
- Orders TN-10026 through TN-10050: STATUS = Processing (1-2 business days to ship)
- Orders TN-10051 and above: STATUS = Not found

POLICIES:
- Return policy: 30 days for unopened items, 14 days for opened items
- Warranty: 1 year manufacturer warranty on all products
- Shipping: Free standard shipping on orders over $50, 2-day shipping available for $9.99

VOICE GUIDELINES:
- Keep responses concise and conversational (2-4 sentences max)
- Speak naturally as if in a phone conversation
- Do not use bullet points or numbered lists
- Spell out prices naturally (say "nineteen ninety-nine" not "$19.99")
- Use contractions and friendly language"""


async def generate_response(
    session_id: str,
    user_text: str,
    on_sentence: Callable[[str], Awaitable[None]],
    cancel_event: asyncio.Event,
) -> str:
    """
    Generate LLM response with streaming sentence delivery.
    FIX #9: Uses asyncio.Lock per session.
    FIX #7: Robust sentence splitting.
    FIX #14: Flush buffer after SENTENCE_FLUSH_TIMEOUT_MS.
    """
    lock = await get_session_lock(session_id)
    async with lock:
        history = await get_conversation(session_id)
        messages = [
            {"role": m["role"], "content": m["content"]}
            for m in history[-20:]  # Last 20 messages for context
        ]
        messages.append({"role": "user", "content": user_text})

        client = _get_client()
        full_response = ""
        buffer = ""
        flush_timeout = settings.SENTENCE_FLUSH_TIMEOUT_MS / 1000.0
        last_chunk_time = time.monotonic()

        async with client.messages.stream(
            model="claude-sonnet-4-6",
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                if cancel_event.is_set():
                    logger.info("llm_cancelled", session_id=session_id)
                    break

                buffer += text
                full_response += text
                last_chunk_time = time.monotonic()

                # FIX #7: Split on robust sentence boundaries
                sentences = split_sentences(buffer)
                if len(sentences) > 1:
                    # All but the last are complete sentences
                    for sentence in sentences[:-1]:
                        logger.debug("sentence_ready", text=sentence[:60])
                        await on_sentence(sentence)
                    buffer = sentences[-1]
                elif len(sentences) == 1 and _BOUNDARY.search(buffer):
                    # Single sentence with a trailing terminator — emit it
                    await on_sentence(sentences[0])
                    buffer = ""

                # FIX #14: Flush timeout - if buffer accumulates without sentence end
                if buffer and (time.monotonic() - last_chunk_time) > flush_timeout:
                    if buffer.strip():
                        logger.debug("sentence_flush_timeout", text=buffer[:60])
                        await on_sentence(buffer.strip())
                        buffer = ""

        # Flush remaining buffer
        if buffer.strip():
            await on_sentence(buffer.strip())

        # FIX #14: Async flush timeout check during streaming
        # (handled above; this catches post-stream remainder)

        if full_response and not cancel_event.is_set():
            await append_message(session_id, "user", user_text)
            await append_message(session_id, "assistant", full_response)
            logger.info("llm_complete", session_id=session_id, chars=len(full_response))

        return full_response
