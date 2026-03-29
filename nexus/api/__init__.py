"""NEXUS FastAPI application — minimal bootstrap for Phase 1."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from nexus import __version__
from nexus.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    settings = get_settings()
    print(f"🚀 NEXUS v{__version__} starting in {settings.env.value} mode")
    yield
    print("🛑 NEXUS shutting down")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="NEXUS API",
        description="Networked Enterprise eXecution & Unified Services",
        version=__version__,
        lifespan=lifespan,
    )

    # Health check
    @app.get("/health")
    async def health():
        return {
            "status": "healthy",
            "version": __version__,
            "environment": settings.env.value,
        }

    return app


app = create_app()
