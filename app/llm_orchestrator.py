from __future__ import annotations
import asyncio
import re
import time
from dataclasses import dataclass
from typing import Callable, Awaitable, cast
import anthropic
from anthropic.types import MessageParam
from app.config import settings
from app.session_manager import get_conversation, append_message, get_session_lock
from app.utils.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class TurnResult:
    """Result of a single LLM generation turn with timing metadata."""
    text: str
    ttfb_ms: float = 0.0
    total_ms: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    model_used: str = ""

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
- Use contractions and friendly language

TOOLS:
You have access to tools for looking up order status, searching products, and scheduling callbacks.
Use them when the customer asks about an order, wants product recommendations, or requests a callback.
After using a tool, summarize the result naturally in your spoken response."""


async def _run_tool_loop(
    client: anthropic.AsyncAnthropic,
    messages: list[dict],
    model: str,
    cancel_event: asyncio.Event,
    on_tool_call: Callable[[str, dict], Awaitable[None]] | None = None,
) -> tuple[list[dict], int, int]:
    """Run the tool_use loop until Claude returns end_turn or max iterations.

    Returns (updated_messages, total_tokens_in, total_tokens_out).
    """
    from app.tools import TOOL_DEFINITIONS, execute_tool

    total_in = 0
    total_out = 0

    for _ in range(settings.MAX_TOOL_ITERATIONS):
        if cancel_event.is_set():
            break

        response = await client.messages.create(
            model=model,
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=cast(list[MessageParam], messages),
            tools=TOOL_DEFINITIONS,
        )
        total_in += response.usage.input_tokens
        total_out += response.usage.output_tokens

        if response.stop_reason != "tool_use":
            # Extract text from content blocks
            text_parts = [b.text for b in response.content if hasattr(b, "text")]
            if text_parts:
                messages.append({"role": "assistant", "content": "".join(text_parts)})
            break

        # Find tool_use block
        tool_block = next((b for b in response.content if b.type == "tool_use"), None)
        if not tool_block:
            break

        if on_tool_call:
            await on_tool_call(tool_block.name, dict(tool_block.input))

        result = await execute_tool(tool_block.name, dict(tool_block.input))

        # Append assistant response + tool result
        messages.append({"role": "assistant", "content": response.content})
        messages.append({
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tool_block.id, "content": result},
            ],
        })

    return messages, total_in, total_out


async def generate_response(
    session_id: str,
    user_text: str,
    on_sentence: Callable[[str], Awaitable[None]],
    cancel_event: asyncio.Event,
    model: str = "claude-sonnet-4-6",
    on_tool_call: Callable[[str, dict], Awaitable[None]] | None = None,
) -> TurnResult:
    """
    Generate LLM response with streaming sentence delivery.
    Returns TurnResult with text, timing metadata, and token counts.
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

        from app.circuit_breaker import llm_circuit, CircuitOpenError

        turn_start = time.monotonic()
        ttfb_ms = 0.0
        first_chunk = True
        tokens_in = 0
        tokens_out = 0
        actual_model = model

        try:
            async with llm_circuit:
                pass  # Pre-check: will raise CircuitOpenError if open
        except CircuitOpenError:
            actual_model = settings.LLM_FALLBACK_MODEL
            logger.warning("llm_circuit_open_fallback", session_id=session_id, fallback=actual_model)

        # Tool use loop (non-streaming) before the streaming response
        if settings.TOOL_USE_ENABLED:
            messages, tool_tokens_in, tool_tokens_out = await _run_tool_loop(
                client=client,
                messages=messages,
                model=actual_model,
                cancel_event=cancel_event,
                on_tool_call=on_tool_call,
            )
            tokens_in += tool_tokens_in
            tokens_out += tool_tokens_out

            # If tool loop already produced a final text response, stream it directly
            last_msg = messages[-1] if messages else {}
            if last_msg.get("role") == "assistant" and isinstance(last_msg.get("content"), str):
                ttfb_ms = (time.monotonic() - turn_start) * 1000
                full_response = last_msg["content"]
                for sentence in split_sentences(full_response):
                    if cancel_event.is_set():
                        break
                    await on_sentence(sentence)

                total_ms = (time.monotonic() - turn_start) * 1000
                if full_response and not cancel_event.is_set():
                    await append_message(session_id, "user", user_text)
                    await append_message(session_id, "assistant", full_response)

                return TurnResult(
                    text=full_response, ttfb_ms=ttfb_ms, total_ms=total_ms,
                    tokens_in=tokens_in, tokens_out=tokens_out, model_used=actual_model,
                )

        async with client.messages.stream(
            model=actual_model,
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=cast(list[MessageParam], messages),
        ) as stream:
            async for text in stream.text_stream:
                if first_chunk:
                    ttfb_ms = (time.monotonic() - turn_start) * 1000
                    first_chunk = False

                if cancel_event.is_set():
                    logger.info("llm_cancelled", session_id=session_id)
                    break

                buffer += text
                full_response += text
                last_chunk_time = time.monotonic()

                # FIX #7: Split on robust sentence boundaries
                sentences = split_sentences(buffer)
                if len(sentences) > 1:
                    for sentence in sentences[:-1]:
                        logger.debug("sentence_ready", text=sentence[:60])
                        await on_sentence(sentence)
                    buffer = sentences[-1]
                elif len(sentences) == 1 and _BOUNDARY.search(buffer):
                    await on_sentence(sentences[0])
                    buffer = ""

                # FIX #14: Flush timeout
                if buffer and (time.monotonic() - last_chunk_time) > flush_timeout:
                    if buffer.strip():
                        logger.debug("sentence_flush_timeout", text=buffer[:60])
                        await on_sentence(buffer.strip())
                        buffer = ""

            # Get token counts from final message
            try:
                final_msg = stream.get_final_message()
                tokens_in = final_msg.usage.input_tokens
                tokens_out = final_msg.usage.output_tokens
            except Exception:
                pass

        total_ms = (time.monotonic() - turn_start) * 1000

        # Flush remaining buffer
        if buffer.strip():
            await on_sentence(buffer.strip())

        if full_response and not cancel_event.is_set():
            await append_message(session_id, "user", user_text)
            await append_message(session_id, "assistant", full_response)
            logger.info(
                "llm_complete",
                session_id=session_id,
                chars=len(full_response),
                ttfb_ms=round(ttfb_ms, 1),
                total_ms=round(total_ms, 1),
                model=actual_model,
            )

        return TurnResult(
            text=full_response,
            ttfb_ms=ttfb_ms,
            total_ms=total_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            model_used=actual_model,
        )
