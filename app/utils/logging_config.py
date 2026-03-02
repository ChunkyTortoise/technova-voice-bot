from __future__ import annotations
import logging
import structlog
from app.config import settings


def configure_logging() -> None:
    """Configure structured logging. JSON in production, pretty in development."""
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        # structlog.stdlib.add_logger_name requires stdlib LoggerFactory, not PrintLoggerFactory
    ]

    if settings.ENVIRONMENT == "development":
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(),
        ]
    else:
        processors = shared_processors + [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Also configure stdlib logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
    )


def get_logger(name: str = "technova"):
    return structlog.get_logger(name)
