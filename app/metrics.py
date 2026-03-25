"""Pipeline latency tracking with P50/P95/P99 percentile computation.

Instruments every voice pipeline component (VAD, STT, LLM, TTS) with
monotonic timers. Maintains a rolling histogram of recent turn timings
for percentile exposure via REST API.
"""
from __future__ import annotations

import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncIterator


@dataclass
class PipelineTimings:
    """Per-turn timing breakdown in milliseconds."""
    stt_ms: float = 0.0
    llm_ttfb_ms: float = 0.0
    llm_total_ms: float = 0.0
    tts_ttfb_ms: float = 0.0
    tts_total_ms: float = 0.0
    e2e_ms: float = 0.0
    session_id: str = ""

    def to_dict(self) -> dict:
        return {
            "stt_ms": round(self.stt_ms, 1),
            "llm_ttfb_ms": round(self.llm_ttfb_ms, 1),
            "llm_total_ms": round(self.llm_total_ms, 1),
            "tts_ttfb_ms": round(self.tts_ttfb_ms, 1),
            "tts_total_ms": round(self.tts_total_ms, 1),
            "e2e_ms": round(self.e2e_ms, 1),
        }


class Timer:
    """Monotonic stopwatch. Use via the timer() context manager."""

    def __init__(self) -> None:
        self._start: float = 0.0
        self._end: float = 0.0

    def start(self) -> None:
        self._start = time.monotonic()

    def stop(self) -> None:
        self._end = time.monotonic()

    @property
    def elapsed_ms(self) -> float:
        end = self._end if self._end else time.monotonic()
        return (end - self._start) * 1000 if self._start else 0.0


@asynccontextmanager
async def timer() -> AsyncIterator[Timer]:
    """Async context manager that tracks elapsed time."""
    t = Timer()
    t.start()
    try:
        yield t
    finally:
        t.stop()


class LatencyHistogram:
    """Rolling histogram of recent pipeline timings for percentile computation."""

    def __init__(self, max_entries: int = 1000) -> None:
        self._entries: deque[PipelineTimings] = deque(maxlen=max_entries)

    def record(self, timings: PipelineTimings) -> None:
        self._entries.append(timings)

    @property
    def count(self) -> int:
        return len(self._entries)

    def get_percentiles(self) -> dict:
        """Compute P50/P95/P99 for each timing field."""
        if not self._entries:
            return {"count": 0, "percentiles": {}}

        fields = ["stt_ms", "llm_ttfb_ms", "llm_total_ms", "tts_total_ms", "e2e_ms"]
        result: dict = {}

        for field_name in fields:
            values = sorted(getattr(e, field_name) for e in self._entries)
            n = len(values)
            result[field_name] = {
                "p50": round(values[int(n * 0.50)], 1),
                "p95": round(values[min(int(n * 0.95), n - 1)], 1),
                "p99": round(values[min(int(n * 0.99), n - 1)], 1),
            }

        return {"count": len(self._entries), "percentiles": result}

    def clear(self) -> None:
        self._entries.clear()


# Module-level singleton
latency_histogram = LatencyHistogram()
