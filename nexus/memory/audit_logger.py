"""Audit Logger — async write to PostgreSQL audit_logs table.

Every agent action is logged BEFORE execution (audit-first principle).
Used by all agents via dependency injection.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


class AuditLogger:
    """Structured audit logging to PostgreSQL.

    Usage:
        audit = AuditLogger(db_session)
        await audit.log_action(
            workflow_id="abc-123",
            agent_name="decision",
            action="classify_request",
            status="success",
            input_data={"text": "..."},
            output_data={"category": "procurement"},
            duration_ms=245,
            llm_tier="tier1",
        )
    """

    def __init__(self, db: AsyncSession | None = None):
        self.db = db
        self._buffer: list[dict] = []

    async def log_action(
        self,
        agent_name: str,
        action: str,
        status: str,
        workflow_id: str | None = None,
        input_data: dict | None = None,
        output_data: dict | None = None,
        error_message: str | None = None,
        duration_ms: int | None = None,
        llm_tier: str | None = None,
    ) -> None:
        """Write a single audit log entry.

        Always logs to structlog. Writes to DB if session is available.
        """
        now = datetime.now(timezone.utc)

        # Always log structured output
        logger.info(
            "audit_log",
            workflow_id=workflow_id,
            agent=agent_name,
            action=action,
            status=status,
            duration_ms=duration_ms,
            llm_tier=llm_tier,
        )

        record = {
            "workflow_id": workflow_id,
            "agent_name": agent_name,
            "action": action,
            "status": status,
            "input_data": json.dumps(input_data) if input_data else None,
            "output_data": json.dumps(output_data) if output_data else None,
            "error_message": error_message,
            "duration_ms": duration_ms,
            "llm_tier": llm_tier,
            "created_at": now,
        }

        if self.db:
            try:
                await self.db.execute(
                    text(
                        "INSERT INTO audit_logs "
                        "(workflow_id, agent_name, action, status, input_data, "
                        "output_data, error_message, duration_ms, llm_tier, created_at) "
                        "VALUES (:workflow_id, :agent_name, :action, :status, "
                        ":input_data, :output_data, :error_message, :duration_ms, "
                        ":llm_tier, :created_at)"
                    ),
                    record,
                )
                await self.db.commit()
            except Exception as e:
                logger.error(
                    "audit_log_db_failed",
                    error=str(e),
                    agent=agent_name,
                    action=action,
                )
                # Buffer for retry — never lose audit data
                self._buffer.append(record)
        else:
            self._buffer.append(record)

    async def flush_buffer(self, db: AsyncSession) -> int:
        """Flush buffered records to DB. Returns count flushed."""
        if not self._buffer:
            return 0

        count = 0
        for record in self._buffer[:]:
            try:
                await db.execute(
                    text(
                        "INSERT INTO audit_logs "
                        "(workflow_id, agent_name, action, status, input_data, "
                        "output_data, error_message, duration_ms, llm_tier, created_at) "
                        "VALUES (:workflow_id, :agent_name, :action, :status, "
                        ":input_data, :output_data, :error_message, :duration_ms, "
                        ":llm_tier, :created_at)"
                    ),
                    record,
                )
                self._buffer.remove(record)
                count += 1
            except Exception as e:
                logger.error("audit_flush_failed", error=str(e))
                break

        if count > 0:
            await db.commit()
            logger.info("audit_buffer_flushed", count=count)

        return count

    @property
    def buffer_size(self) -> int:
        return len(self._buffer)
