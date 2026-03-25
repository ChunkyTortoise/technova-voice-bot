"""Per-call cost tracking for voice pipeline.

Computes USD costs from Deepgram STT/TTS pricing and Anthropic token pricing.
Aggregates per-session and overall costs for budget visibility.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from app.config import settings


@dataclass
class TurnCost:
    """Cost breakdown for a single voice turn."""
    stt_cost: float = 0.0
    llm_cost: float = 0.0
    tts_cost: float = 0.0
    total_cost: float = 0.0
    model_used: str = ""
    session_id: str = ""

    def to_dict(self) -> dict:
        return {
            "stt_cost": round(self.stt_cost, 6),
            "llm_cost": round(self.llm_cost, 6),
            "tts_cost": round(self.tts_cost, 6),
            "total_cost": round(self.total_cost, 6),
            "model_used": self.model_used,
        }


def compute_turn_cost(
    audio_duration_sec: float,
    tokens_in: int,
    tokens_out: int,
    tts_chars: int,
    model: str = "claude-sonnet-4-6",
) -> TurnCost:
    """Compute the USD cost of a single voice turn.

    Pricing (as of 2026):
    - Deepgram STT Nova-3: $0.0043/min
    - Anthropic Sonnet: $3/M input, $15/M output
    - Anthropic Haiku: $0.25/M input, $1.25/M output
    - Deepgram TTS Aura-2: $0.011/1K chars
    """
    # STT cost
    stt_minutes = audio_duration_sec / 60.0
    stt_cost = stt_minutes * settings.COST_STT_PER_MINUTE

    # LLM cost (model-aware)
    if "haiku" in model.lower():
        llm_cost = (
            tokens_in * settings.COST_LLM_HAIKU_INPUT_PER_1K / 1000
            + tokens_out * settings.COST_LLM_HAIKU_OUTPUT_PER_1K / 1000
        )
    else:
        llm_cost = (
            tokens_in * settings.COST_LLM_INPUT_PER_1K / 1000
            + tokens_out * settings.COST_LLM_OUTPUT_PER_1K / 1000
        )

    # TTS cost
    tts_cost = (tts_chars / 1000) * settings.COST_TTS_PER_1K_CHARS

    total = stt_cost + llm_cost + tts_cost

    return TurnCost(
        stt_cost=stt_cost,
        llm_cost=llm_cost,
        tts_cost=tts_cost,
        total_cost=total,
        model_used=model,
    )


class CostAggregator:
    """Aggregates per-turn costs for reporting."""

    def __init__(self, max_entries: int = 10_000) -> None:
        self._entries: deque[TurnCost] = deque(maxlen=max_entries)
        self._session_costs: dict[str, float] = {}

    def record(self, session_id: str, cost: TurnCost) -> None:
        cost.session_id = session_id
        self._entries.append(cost)
        self._session_costs[session_id] = (
            self._session_costs.get(session_id, 0.0) + cost.total_cost
        )

    def get_session_total(self, session_id: str) -> float:
        return round(self._session_costs.get(session_id, 0.0), 6)

    def get_summary(self) -> dict:
        if not self._entries:
            return {
                "total_turns": 0,
                "total_cost_usd": 0.0,
                "avg_cost_per_turn": 0.0,
                "cost_by_component": {"stt": 0.0, "llm": 0.0, "tts": 0.0},
            }

        total_stt = sum(e.stt_cost for e in self._entries)
        total_llm = sum(e.llm_cost for e in self._entries)
        total_tts = sum(e.tts_cost for e in self._entries)
        total = total_stt + total_llm + total_tts
        count = len(self._entries)

        return {
            "total_turns": count,
            "total_cost_usd": round(total, 6),
            "avg_cost_per_turn": round(total / count, 6) if count else 0.0,
            "cost_by_component": {
                "stt": round(total_stt, 6),
                "llm": round(total_llm, 6),
                "tts": round(total_tts, 6),
            },
        }

    def clear(self) -> None:
        self._entries.clear()
        self._session_costs.clear()


# Module-level singleton
cost_aggregator = CostAggregator()
