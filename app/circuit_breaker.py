"""Async circuit breaker for voice pipeline resilience.

Wraps external service calls (Deepgram STT, Anthropic LLM, Deepgram TTS)
with automatic failure detection and recovery. Same pattern as docextract
for consistent portfolio narrative.

States: CLOSED (normal) -> OPEN (failing, reject calls) -> HALF_OPEN (testing recovery)
"""
from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import Any


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """Raised when a call is attempted on an open circuit."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Circuit '{name}' is OPEN — call rejected")


class AsyncCircuitBreaker:
    """Per-service circuit breaker with automatic state transitions.

    Usage:
        async with llm_circuit:
            result = await call_llm(...)
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 1,
    ) -> None:
        self.name = name
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._half_open_max_calls = half_open_max_calls

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._half_open_calls = 0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        # Auto-transition from OPEN to HALF_OPEN after recovery timeout
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time >= self._recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
        return self._state

    async def __aenter__(self) -> "AsyncCircuitBreaker":
        async with self._lock:
            current = self.state
            if current == CircuitState.OPEN:
                raise CircuitOpenError(self.name)
            if current == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self._half_open_max_calls:
                    raise CircuitOpenError(self.name)
                self._half_open_calls += 1
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        async with self._lock:
            if exc_type is not None:
                self._failure_count += 1
                self._last_failure_time = time.monotonic()
                if self._state == CircuitState.HALF_OPEN:
                    # Failed during probe — re-open
                    self._state = CircuitState.OPEN
                elif self._failure_count >= self._failure_threshold:
                    self._state = CircuitState.OPEN
            else:
                if self._state == CircuitState.HALF_OPEN:
                    # Probe succeeded — close circuit
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                elif self._state == CircuitState.CLOSED:
                    # Reset consecutive failure count on success
                    self._failure_count = 0

    def reset(self) -> None:
        """Manually reset the circuit breaker to CLOSED state."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._half_open_calls = 0
        self._last_failure_time = 0.0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
        }


# Module-level instances for each external service
llm_circuit = AsyncCircuitBreaker("llm", failure_threshold=3, recovery_timeout=30.0)
stt_circuit = AsyncCircuitBreaker("stt", failure_threshold=3, recovery_timeout=30.0)
tts_circuit = AsyncCircuitBreaker("tts", failure_threshold=3, recovery_timeout=30.0)
