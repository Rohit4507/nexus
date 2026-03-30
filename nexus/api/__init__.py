"""NEXUS FastAPI application — Phase 3: Tool Integration wired."""

from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from nexus import __version__
from nexus.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    settings = get_settings()
    print(f"🚀 NEXUS v{__version__} starting in {settings.env.value} mode")
    print(f"   Ollama: {settings.ollama_url}")
    print(f"   Database: {settings.db_host}:{settings.db_port}/{settings.db_name}")

    # Initialize tool registry
    from nexus.tools.registry import ToolRegistry
    app.state.tool_registry = ToolRegistry.from_settings()
    print(f"   Tools: {app.state.tool_registry.tool_names}")

    # Start SLA Monitor background polling
    from nexus.agents.sla_monitor import poll_slas
    app.state.sla_task = asyncio.create_task(poll_slas(interval_seconds=60))
    print("   SLA Monitor started (60s loop)")

    yield

    # Shutdown
    if app.state.sla_task:
        app.state.sla_task.cancel()
        
    await app.state.tool_registry.close_all()
    print("🛑 NEXUS shutting down")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="NEXUS API",
        description="Networked Enterprise eXecution & Unified Services",
        version=__version__,
        lifespan=lifespan,
    )

    # ── Health check ─────────────────────────────────────────
    @app.get("/health")
    async def health():
        return {
            "status": "healthy",
            "version": __version__,
            "environment": settings.env.value,
        }

    @app.get("/health/tools")
    async def tools_health(request):
        """Health check for all registered integration tools."""
        registry = request.app.state.tool_registry
        results = await registry.health_check_all()
        all_healthy = all(r["healthy"] for r in results.values())
        return {
            "status": "healthy" if all_healthy else "degraded",
            "tools": results,
        }

    # ── Register route modules ───────────────────────────────
    from nexus.api.routes import router as workflows_router
    from nexus.api.routes.approvals import router as approvals_router
    from nexus.api.routes.webhooks import router as webhooks_router
    from nexus.api.routes.meetings import router as meetings_router

    app.include_router(workflows_router)
    app.include_router(approvals_router)
    app.include_router(webhooks_router)
    app.include_router(meetings_router)

    # ── Prometheus Metrics ───────────────────────────────────
    Instrumentator().instrument(app).expose(app, endpoint="/metrics")

    return app


app = create_app()
