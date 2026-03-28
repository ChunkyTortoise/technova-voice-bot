from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import Column, String, DateTime, Text, ForeignKey, select
from sqlalchemy.orm import DeclarativeBase, relationship
from app.config import settings
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

engine = create_async_engine(settings.DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Session(Base):
    __tablename__ = "sessions"
    id = Column(String, primary_key=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    messages = relationship("Message", back_populates="session", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    session = relationship("Session", back_populates="messages")


class ExecutiveReport(Base):
    __tablename__ = "executive_reports"
    id = Column(String, primary_key=True)
    generated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    date_from = Column(DateTime(timezone=True), nullable=True)
    date_to = Column(DateTime(timezone=True), nullable=True)
    format = Column(String, nullable=False, default="both")
    files_json = Column(Text, nullable=False, default="[]")
    summary_json = Column(Text, nullable=False, default="{}")


async def init_db() -> None:
    """Create all tables on startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("database_initialized", url=settings.DATABASE_URL)


async def create_session(session_id: str) -> None:
    async with AsyncSessionLocal() as db:
        db.add(Session(id=session_id))
        await db.commit()


async def save_message(session_id: str, role: str, content: str) -> None:
    async with AsyncSessionLocal() as db:
        db.add(Message(session_id=session_id, role=role, content=content))
        await db.commit()


async def get_session_history(session_id: str) -> list[dict]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.timestamp)
        )
        messages = result.scalars().all()
        return [
            {
                "role": m.role,
                "content": m.content,
                "timestamp": m.timestamp.isoformat() if m.timestamp else None,
            }
            for m in messages
        ]


async def save_executive_report(
    report_id: str,
    *,
    date_from: datetime | None,
    date_to: datetime | None,
    report_format: str,
    files_json: str,
    summary_json: str,
) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            ExecutiveReport(
                id=report_id,
                date_from=date_from,
                date_to=date_to,
                format=report_format,
                files_json=files_json,
                summary_json=summary_json,
            )
        )
        await db.commit()


async def get_executive_report(report_id: str) -> ExecutiveReport | None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ExecutiveReport).where(ExecutiveReport.id == report_id))
        return result.scalar_one_or_none()


async def list_executive_reports(limit: int = 20) -> list[ExecutiveReport]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ExecutiveReport).order_by(ExecutiveReport.generated_at.desc()).limit(limit)
        )
        return list(result.scalars().all())
