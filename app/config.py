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


settings = Settings()
