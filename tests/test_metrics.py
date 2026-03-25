"""Unit tests for pipeline latency tracking."""
from __future__ import annotations

import asyncio
import pytest
from app.metrics import LatencyHistogram, PipelineTimings, Timer, timer
from app.llm_orchestrator import TurnResult


# ---------------------------------------------------------------------------
# Timer
# ---------------------------------------------------------------------------

class TestTimer:
    def test_timer_measures_elapsed(self):
        t = Timer()
        t.start()
        # Busy wait a tiny bit
        import time
        time.sleep(0.01)
        t.stop()
        assert t.elapsed_ms > 5  # At least 5ms
        assert t.elapsed_ms < 500  # Not absurdly long

    def test_timer_zero_before_start(self):
        t = Timer()
        assert t.elapsed_ms == 0.0

    def test_timer_elapsed_before_stop_is_running(self):
        t = Timer()
        t.start()
        assert t.elapsed_ms > 0  # Still running

    @pytest.mark.asyncio
    async def test_timer_context_manager(self):
        async with timer() as t:
            await asyncio.sleep(0.01)
        assert t.elapsed_ms >= 5
        assert t.elapsed_ms < 500


# ---------------------------------------------------------------------------
# PipelineTimings
# ---------------------------------------------------------------------------

class TestPipelineTimings:
    def test_default_values(self):
        pt = PipelineTimings()
        assert pt.stt_ms == 0.0
        assert pt.llm_ttfb_ms == 0.0
        assert pt.e2e_ms == 0.0

    def test_to_dict(self):
        pt = PipelineTimings(stt_ms=100.123, llm_ttfb_ms=50.456, e2e_ms=500.789)
        d = pt.to_dict()
        assert d["stt_ms"] == 100.1
        assert d["llm_ttfb_ms"] == 50.5
        assert d["e2e_ms"] == 500.8

    def test_session_id_stored(self):
        pt = PipelineTimings(session_id="abc-123")
        assert pt.session_id == "abc-123"


# ---------------------------------------------------------------------------
# LatencyHistogram
# ---------------------------------------------------------------------------

class TestLatencyHistogram:
    def test_empty_histogram_returns_empty(self):
        h = LatencyHistogram()
        result = h.get_percentiles()
        assert result["count"] == 0
        assert result["percentiles"] == {}

    def test_single_entry(self):
        h = LatencyHistogram()
        h.record(PipelineTimings(stt_ms=100, llm_ttfb_ms=50, e2e_ms=300))
        result = h.get_percentiles()
        assert result["count"] == 1
        assert result["percentiles"]["stt_ms"]["p50"] == 100.0

    def test_percentiles_computed_correctly(self):
        h = LatencyHistogram()
        for i in range(100):
            h.record(PipelineTimings(e2e_ms=float(i + 1)))
        result = h.get_percentiles()
        assert result["count"] == 100
        # P50 should be around 50
        assert 49 <= result["percentiles"]["e2e_ms"]["p50"] <= 51
        # P95 should be around 95
        assert 94 <= result["percentiles"]["e2e_ms"]["p95"] <= 96

    def test_max_entries_enforced(self):
        h = LatencyHistogram(max_entries=10)
        for i in range(20):
            h.record(PipelineTimings(e2e_ms=float(i)))
        assert h.count == 10

    def test_clear_resets(self):
        h = LatencyHistogram()
        h.record(PipelineTimings(e2e_ms=100))
        h.clear()
        assert h.count == 0

    def test_all_fields_tracked(self):
        h = LatencyHistogram()
        h.record(PipelineTimings(
            stt_ms=10, llm_ttfb_ms=20, llm_total_ms=30,
            tts_total_ms=40, e2e_ms=50,
        ))
        result = h.get_percentiles()
        fields = result["percentiles"]
        assert "stt_ms" in fields
        assert "llm_ttfb_ms" in fields
        assert "llm_total_ms" in fields
        assert "tts_total_ms" in fields
        assert "e2e_ms" in fields


# ---------------------------------------------------------------------------
# TurnResult
# ---------------------------------------------------------------------------

class TestTurnResult:
    def test_turn_result_fields(self):
        tr = TurnResult(
            text="Hello",
            ttfb_ms=100.5,
            total_ms=500.0,
            tokens_in=50,
            tokens_out=30,
            model_used="claude-sonnet-4-6",
        )
        assert tr.text == "Hello"
        assert tr.ttfb_ms == 100.5
        assert tr.tokens_in == 50
        assert tr.model_used == "claude-sonnet-4-6"

    def test_turn_result_defaults(self):
        tr = TurnResult(text="Hi")
        assert tr.ttfb_ms == 0.0
        assert tr.tokens_in == 0
        assert tr.model_used == ""
