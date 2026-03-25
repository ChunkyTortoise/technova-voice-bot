from __future__ import annotations
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str = "sqlite+aiosqlite:///./data/technova.db"
    REDIS_URL: str = "redis://localhost:6379"
    DEEPGRAM_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    # FIX #6: Secure CORS default (not *)
    CORS_ORIGINS: list[str] = ["http://localhost:8000"]
    SESSION_TTL_SECONDS: int = 1800  # 30 min
    LOCK_TTL_SECONDS: int = 30  # FIX #9: extended from 10s to 30s
    MAX_CONCURRENT_WS_PER_IP: int = 5  # FIX #8: rate limit
    ENVIRONMENT: str = "development"
    VERSION: str = "1.0.0"
    SENTENCE_FLUSH_TIMEOUT_MS: int = 500  # FIX #7, #14: flush buffer after 500ms
    ADMIN_API_KEY: str = ""
    OPERATOR_API_KEY: str = ""
    VIEWER_API_KEY: str = ""

    # Circuit breaker
    LLM_FALLBACK_MODEL: str = "claude-haiku-4-5-20251001"
    CIRCUIT_BREAKER_THRESHOLD: int = 3
    CIRCUIT_BREAKER_RECOVERY_SEC: float = 30.0

    # Tool use / function calling
    TOOL_USE_ENABLED: bool = True
    MAX_TOOL_ITERATIONS: int = 3

    # Cost tracking (USD pricing)
    COST_STT_PER_MINUTE: float = 0.0043        # Deepgram Nova-3
    COST_LLM_INPUT_PER_1K: float = 0.003       # Claude Sonnet input
    COST_LLM_OUTPUT_PER_1K: float = 0.015      # Claude Sonnet output
    COST_LLM_HAIKU_INPUT_PER_1K: float = 0.00025   # Claude Haiku input
    COST_LLM_HAIKU_OUTPUT_PER_1K: float = 0.00125  # Claude Haiku output
    COST_TTS_PER_1K_CHARS: float = 0.011       # Deepgram Aura-2


settings = Settings()
