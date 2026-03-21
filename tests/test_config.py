from __future__ import annotations
import pytest
from unittest.mock import patch


def test_settings_defaults():
    """Default values are present and sensible."""
    from app.config import Settings
    s = Settings()
    assert s.DATABASE_URL.startswith("sqlite+aiosqlite://")
    assert s.REDIS_URL == "redis://localhost:6379"
    assert s.SESSION_TTL_SECONDS == 1800
    assert s.LOCK_TTL_SECONDS == 30
    assert s.MAX_CONCURRENT_WS_PER_IP == 5
    assert s.ENVIRONMENT == "development"
    assert s.VERSION == "1.0.0"
    assert s.SENTENCE_FLUSH_TIMEOUT_MS == 500


def test_deepgram_api_key_defaults_empty():
    """DEEPGRAM_API_KEY defaults to empty string (triggers demo mode)."""
    from app.config import Settings
    s = Settings()
    assert s.DEEPGRAM_API_KEY == ""


def test_anthropic_api_key_defaults_empty():
    """ANTHROPIC_API_KEY defaults to empty string."""
    from app.config import Settings
    s = Settings()
    assert s.ANTHROPIC_API_KEY == ""


def test_cors_origins_default_is_localhost():
    """CORS default restricts to localhost (not wildcard)."""
    from app.config import Settings
    s = Settings()
    assert "http://localhost:8000" in s.CORS_ORIGINS
    assert "*" not in s.CORS_ORIGINS


def test_demo_mode_when_deepgram_key_missing():
    """DEMO_MODE is True when DEEPGRAM_API_KEY is absent."""
    with patch.dict("os.environ", {"DEEPGRAM_API_KEY": "", "ANTHROPIC_API_KEY": "sk-test"}, clear=False):
        from app.config import Settings
        s = Settings()
        demo = not s.DEEPGRAM_API_KEY or not s.ANTHROPIC_API_KEY
        assert demo is True


def test_demo_mode_when_anthropic_key_missing():
    """DEMO_MODE is True when ANTHROPIC_API_KEY is absent."""
    with patch.dict("os.environ", {"DEEPGRAM_API_KEY": "dg-test", "ANTHROPIC_API_KEY": ""}, clear=False):
        from app.config import Settings
        s = Settings()
        demo = not s.DEEPGRAM_API_KEY or not s.ANTHROPIC_API_KEY
        assert demo is True


def test_demo_mode_false_when_both_keys_present():
    """DEMO_MODE is False when both API keys are set."""
    with patch.dict("os.environ", {"DEEPGRAM_API_KEY": "dg-test", "ANTHROPIC_API_KEY": "sk-test"}, clear=False):
        from app.config import Settings
        s = Settings()
        demo = not s.DEEPGRAM_API_KEY or not s.ANTHROPIC_API_KEY
        assert demo is False


def test_settings_accepts_custom_env_vars():
    """Environment variables override defaults."""
    with patch.dict("os.environ", {"SESSION_TTL_SECONDS": "3600", "ENVIRONMENT": "production"}, clear=False):
        from app.config import Settings
        s = Settings()
        assert s.SESSION_TTL_SECONDS == 3600
        assert s.ENVIRONMENT == "production"


def test_cors_origins_accepts_list_override():
    """CORS_ORIGINS can be overridden via env."""
    with patch.dict("os.environ", {"CORS_ORIGINS": '["https://example.com"]'}, clear=False):
        from app.config import Settings
        s = Settings()
        assert "https://example.com" in s.CORS_ORIGINS


def test_max_concurrent_ws_per_ip_default():
    """Rate limit default is 5 connections per IP."""
    from app.config import Settings
    s = Settings()
    assert s.MAX_CONCURRENT_WS_PER_IP == 5


def test_admin_operator_viewer_keys_default_empty():
    """RBAC API keys default to empty (unauthenticated until configured)."""
    from app.config import Settings
    s = Settings()
    assert s.ADMIN_API_KEY == ""
    assert s.OPERATOR_API_KEY == ""
    assert s.VIEWER_API_KEY == ""
