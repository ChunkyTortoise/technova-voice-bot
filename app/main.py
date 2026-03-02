from __future__ import annotations
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.config import settings
from app.database import init_db
from app.session_manager import close_redis
from app.routes_rest import router as rest_router
from app.routes_websocket import router as ws_router
from app.utils.logging_config import configure_logging, get_logger
import os

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    logger.info("startup_begin", version=settings.VERSION, env=settings.ENVIRONMENT)
    # Ensure data directory exists (for SQLite)
    os.makedirs("data", exist_ok=True)
    await init_db()
    logger.info("startup_complete")
    yield
    await close_redis()
    logger.info("shutdown_complete")


app = FastAPI(
    title="TechNova Voice AI",
    version=settings.VERSION,
    lifespan=lifespan,
)

# FIX #6: Secure CORS - use configured origins, not *
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(rest_router)
app.include_router(ws_router)

# Serve frontend
static_path = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.exists(static_path):
    app.mount("/", StaticFiles(directory=static_path, html=True), name="static")
