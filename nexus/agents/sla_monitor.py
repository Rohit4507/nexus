"""SLA Monitor Background Service — 60s polling loop for SLA breaches."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog
from sqlalchemy import text

from nexus.database import async_session_factory
from nexus.agents.monitoring import MonitoringAgent
from nexus.memory.audit_logger import AuditLogger

logger = structlog.get_logger()


async def poll_slas(interval_seconds: int = 60):
    """Background task to poll in-progress workflows against SLA bounds."""
    logger.info("sla_monitor_started", interval=interval_seconds)

    while True:
        try:
            await asyncio.sleep(interval_seconds)
            await _check_all_active_workflows()
        except asyncio.CancelledError:
            logger.info("sla_monitor_stopped")
            break
        except Exception as e:
            logger.error("sla_monitor_loop_crashed", error=str(e))


async def _check_all_active_workflows():
    """Query DB for active workflows and run them through MonitoringAgent."""
    start = datetime.now(timezone.utc)
    evaluated = 0
    warnings = 0
    breaches = 0

    async with async_session_factory() as session:
        audit = AuditLogger(session)
        monitor = MonitoringAgent(session, audit)

        # Get all actively running workflows
        result = await session.execute(
            text("SELECT id, workflow_type, created_at, status FROM workflows WHERE status = 'pending' OR status = 'in_progress'")
        )
        rows = result.mappings().all()

        for row in rows:
            workflow_dict = {
                "workflow_id": str(row["id"]),
                "workflow_type": row["workflow_type"],
                "created_at": row["created_at"],
            }
            
            # MonitoringAgent calculates the ratio and logs warnings/breaches natively
            status_result = await monitor.check_sla(workflow_dict)
            evaluated += 1
            
            if status_result["status"] == "warning":
                warnings += 1
            elif status_result["status"] == "breached":
                breaches += 1
                
                # Escalation action: Update DB status directly to prevent further SLA deterioration unchecked
                await session.execute(
                    text("UPDATE workflows SET status = 'escalated' WHERE id = :id"),
                    {"id": row["id"]}
                )

        if evaluated > 0:
            await session.commit()
            duration_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
            logger.info(
                "sla_scan_complete", 
                evaluated=evaluated, 
                warnings=warnings, 
                breaches=breaches, 
                duration_ms=duration_ms
            )
