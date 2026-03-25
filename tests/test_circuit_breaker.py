"""Unit tests for async circuit breaker."""
from __future__ import annotations

import asyncio
import time
import pytest
from app.circuit_breaker import (
    AsyncCircuitBreaker,
    CircuitOpenError,
    CircuitState,
)


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------

class TestCircuitBreakerStates:
    @pytest.mark.asyncio
    async def test_starts_closed(self):
        cb = AsyncCircuitBreaker("test", failure_threshold=3)
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_stays_closed_on_success(self):
        cb = AsyncCircuitBreaker("test", failure_threshold=3)
        async with cb:
            pass
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_opens_after_threshold_failures(self):
        cb = AsyncCircuitBreaker("test", failure_threshold=2)
        for _ in range(2):
            with pytest.raises(ValueError):
                async with cb:
                    raise ValueError("fail")
        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_rejects_calls_when_open(self):
        cb = AsyncCircuitBreaker("test", failure_threshold=1, recovery_timeout=60)
        with pytest.raises(ValueError):
            async with cb:
                raise ValueError("fail")
        assert cb.state == CircuitState.OPEN

        with pytest.raises(CircuitOpenError):
            async with cb:
                pass

    @pytest.mark.asyncio
    async def test_transitions_to_half_open_after_timeout(self):
        cb = AsyncCircuitBreaker("test", failure_threshold=1, recovery_timeout=0.05)
        with pytest.raises(ValueError):
            async with cb:
                raise ValueError("fail")
        assert cb.state == CircuitState.OPEN

        await asyncio.sleep(0.06)
        assert cb.state == CircuitState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_half_open_closes_on_success(self):
        cb = AsyncCircuitBreaker("test", failure_threshold=1, recovery_timeout=0.05)
        with pytest.raises(ValueError):
            async with cb:
                raise ValueError("fail")

        await asyncio.sleep(0.06)
        assert cb.state == CircuitState.HALF_OPEN

        async with cb:
            pass  # Success
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_half_open_reopens_on_failure(self):
        cb = AsyncCircuitBreaker("test", failure_threshold=1, recovery_timeout=0.05)
        with pytest.raises(ValueError):
            async with cb:
                raise ValueError("fail")

        await asyncio.sleep(0.06)
        with pytest.raises(ValueError):
            async with cb:
                raise ValueError("fail again")
        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_success_resets_failure_count(self):
        cb = AsyncCircuitBreaker("test", failure_threshold=3)
        # 2 failures
        for _ in range(2):
            with pytest.raises(ValueError):
                async with cb:
                    raise ValueError("fail")
        assert cb._failure_count == 2
        # 1 success resets
        async with cb:
            pass
        assert cb._failure_count == 0


# ---------------------------------------------------------------------------
# CircuitOpenError
# ---------------------------------------------------------------------------

class TestCircuitOpenError:
    @pytest.mark.asyncio
    async def test_error_contains_circuit_name(self):
        cb = AsyncCircuitBreaker("my-service", failure_threshold=1, recovery_timeout=60)
        with pytest.raises(ValueError):
            async with cb:
                raise ValueError("fail")
        with pytest.raises(CircuitOpenError) as exc_info:
            async with cb:
                pass
        assert "my-service" in str(exc_info.value)
        assert exc_info.value.name == "my-service"


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------

class TestReset:
    @pytest.mark.asyncio
    async def test_reset_returns_to_closed(self):
        cb = AsyncCircuitBreaker("test", failure_threshold=1)
        with pytest.raises(ValueError):
            async with cb:
                raise ValueError("fail")
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb._failure_count == 0


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------

class TestToDict:
    @pytest.mark.asyncio
    async def test_to_dict_structure(self):
        cb = AsyncCircuitBreaker("llm", failure_threshold=3)
        d = cb.to_dict()
        assert d["name"] == "llm"
        assert d["state"] == "closed"
        assert d["failure_count"] == 0

    @pytest.mark.asyncio
    async def test_to_dict_reflects_state(self):
        cb = AsyncCircuitBreaker("stt", failure_threshold=1, recovery_timeout=60)
        with pytest.raises(ValueError):
            async with cb:
                raise ValueError("fail")
        d = cb.to_dict()
        assert d["state"] == "open"
        assert d["failure_count"] == 1


# ---------------------------------------------------------------------------
# Half-open max calls
# ---------------------------------------------------------------------------

class TestHalfOpenLimit:
    @pytest.mark.asyncio
    async def test_half_open_rejects_excess_calls(self):
        cb = AsyncCircuitBreaker("test", failure_threshold=1, recovery_timeout=0.05, half_open_max_calls=1)
        with pytest.raises(ValueError):
            async with cb:
                raise ValueError("fail")
        await asyncio.sleep(0.06)

        # First call in half-open should be allowed
        assert cb.state == CircuitState.HALF_OPEN
        # Manually increment half_open_calls to simulate first call consumed
        cb._half_open_calls = 1

        with pytest.raises(CircuitOpenError):
            async with cb:
                pass
