"""SQLAlchemy async engine and session factory."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from nexus.config import get_settings


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""
    pass


def _build_engine():
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        echo=(settings.log_level == "DEBUG"),
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
    )


engine = _build_engine()

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    """FastAPI dependency — yields a DB session, auto-closes."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
