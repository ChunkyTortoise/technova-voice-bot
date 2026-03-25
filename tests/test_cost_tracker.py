"""Unit tests for per-call cost tracking."""
from __future__ import annotations

import pytest
from app.cost_tracker import CostAggregator, TurnCost, compute_turn_cost


# ---------------------------------------------------------------------------
# compute_turn_cost
# ---------------------------------------------------------------------------

class TestComputeTurnCost:
    def test_sonnet_pricing(self):
        cost = compute_turn_cost(
            audio_duration_sec=60,  # 1 minute
            tokens_in=1000,
            tokens_out=200,
            tts_chars=500,
            model="claude-sonnet-4-6",
        )
        # STT: 1 min * $0.0043 = $0.0043
        assert cost.stt_cost == pytest.approx(0.0043, abs=0.0001)
        # LLM: 1000 * 0.003/1000 + 200 * 0.015/1000 = 0.003 + 0.003 = 0.006
        assert cost.llm_cost == pytest.approx(0.006, abs=0.0001)
        # TTS: 0.5 * $0.011 = $0.0055
        assert cost.tts_cost == pytest.approx(0.0055, abs=0.0001)
        assert cost.total_cost == pytest.approx(0.0158, abs=0.001)

    def test_haiku_pricing_cheaper(self):
        sonnet_cost = compute_turn_cost(
            audio_duration_sec=30, tokens_in=500, tokens_out=100,
            tts_chars=200, model="claude-sonnet-4-6",
        )
        haiku_cost = compute_turn_cost(
            audio_duration_sec=30, tokens_in=500, tokens_out=100,
            tts_chars=200, model="claude-haiku-4-5-20251001",
        )
        assert haiku_cost.llm_cost < sonnet_cost.llm_cost
        assert haiku_cost.total_cost < sonnet_cost.total_cost

    def test_zero_inputs(self):
        cost = compute_turn_cost(
            audio_duration_sec=0, tokens_in=0, tokens_out=0,
            tts_chars=0, model="claude-sonnet-4-6",
        )
        assert cost.total_cost == 0.0

    def test_model_stored_in_result(self):
        cost = compute_turn_cost(
            audio_duration_sec=10, tokens_in=100, tokens_out=50,
            tts_chars=100, model="claude-sonnet-4-6",
        )
        assert cost.model_used == "claude-sonnet-4-6"

    def test_to_dict(self):
        cost = compute_turn_cost(
            audio_duration_sec=30, tokens_in=200, tokens_out=50,
            tts_chars=150, model="claude-sonnet-4-6",
        )
        d = cost.to_dict()
        assert "stt_cost" in d
        assert "llm_cost" in d
        assert "tts_cost" in d
        assert "total_cost" in d
        assert "model_used" in d


# ---------------------------------------------------------------------------
# CostAggregator
# ---------------------------------------------------------------------------

class TestCostAggregator:
    def test_empty_summary(self):
        agg = CostAggregator()
        s = agg.get_summary()
        assert s["total_turns"] == 0
        assert s["total_cost_usd"] == 0.0

    def test_record_and_summary(self):
        agg = CostAggregator()
        cost = TurnCost(stt_cost=0.01, llm_cost=0.02, tts_cost=0.005, total_cost=0.035)
        agg.record("s1", cost)
        s = agg.get_summary()
        assert s["total_turns"] == 1
        assert s["total_cost_usd"] == pytest.approx(0.035, abs=0.001)

    def test_per_session_accumulation(self):
        agg = CostAggregator()
        agg.record("s1", TurnCost(total_cost=0.01))
        agg.record("s1", TurnCost(total_cost=0.02))
        agg.record("s2", TurnCost(total_cost=0.05))
        assert agg.get_session_total("s1") == pytest.approx(0.03, abs=0.001)
        assert agg.get_session_total("s2") == pytest.approx(0.05, abs=0.001)

    def test_unknown_session_returns_zero(self):
        agg = CostAggregator()
        assert agg.get_session_total("nonexistent") == 0.0

    def test_cost_by_component(self):
        agg = CostAggregator()
        agg.record("s1", TurnCost(stt_cost=0.01, llm_cost=0.02, tts_cost=0.005, total_cost=0.035))
        agg.record("s1", TurnCost(stt_cost=0.01, llm_cost=0.03, tts_cost=0.005, total_cost=0.045))
        s = agg.get_summary()
        assert s["cost_by_component"]["stt"] == pytest.approx(0.02, abs=0.001)
        assert s["cost_by_component"]["llm"] == pytest.approx(0.05, abs=0.001)

    def test_avg_cost_per_turn(self):
        agg = CostAggregator()
        agg.record("s1", TurnCost(stt_cost=0.005, llm_cost=0.01, tts_cost=0.005, total_cost=0.02))
        agg.record("s1", TurnCost(stt_cost=0.01, llm_cost=0.02, tts_cost=0.01, total_cost=0.04))
        s = agg.get_summary()
        assert s["avg_cost_per_turn"] == pytest.approx(0.03, abs=0.001)

    def test_clear(self):
        agg = CostAggregator()
        agg.record("s1", TurnCost(total_cost=0.05))
        agg.clear()
        assert agg.get_summary()["total_turns"] == 0
        assert agg.get_session_total("s1") == 0.0
