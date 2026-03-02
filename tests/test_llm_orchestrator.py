from __future__ import annotations

from app.llm_orchestrator import split_sentences


def test_sentence_split_simple():
    text = "Hello there. How can I help you? I am ready."
    parts = split_sentences(text)
    assert len(parts) == 3
    assert parts[0] == "Hello there"
    assert parts[1] == "How can I help you"
    assert parts[2] == "I am ready."


def test_sentence_split_price_not_split():
    """FIX #7: $19.99 should not trigger a sentence split."""
    text = "The price is $19.99 and that includes shipping."
    parts = split_sentences(text)
    # No split: digit before period prevents boundary
    assert len(parts) == 1, f"Expected 1 part but got {len(parts)}: {parts}"


def test_sentence_split_abbreviation_not_split():
    """FIX #7: 'Dr. Smith' should not trigger a sentence split."""
    text = "Dr. Smith will help you today. Please hold."
    parts = split_sentences(text)
    # "Dr. Smith will help you today" should be one chunk
    assert len(parts) == 2
    assert "Smith" in parts[0], f"Expected Smith in first part, got: {parts}"


def test_sentence_split_exclamation():
    text = "Great news! Your order has shipped."
    parts = split_sentences(text)
    assert len(parts) == 2
    assert parts[0] == "Great news"


def test_sentence_split_question():
    text = "Can I help you? Sure I can."
    parts = split_sentences(text)
    assert len(parts) == 2


def test_sentence_split_ellipsis_not_fragmented():
    """FIX #7: '...' should not cause 3 empty splits."""
    text = "Let me check... your order status."
    parts = split_sentences(text)
    # Should not produce empty strings from the ellipsis
    assert all(len(p) > 0 for p in parts)


def test_sentence_split_double_newline():
    text = "First paragraph.\n\nSecond paragraph."
    parts = split_sentences(text)
    assert len(parts) == 2
