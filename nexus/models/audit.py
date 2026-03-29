"""Audit & operational health models: audit_logs, agent_health, failed_triggers."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
    ForeignKey,
    Index,
    Numeric,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nexus.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Audit Logs ───────────────────────────────────────────────────────────────

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id"), nullable=True
    )
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(200), nullable=False)
    input_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    output_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    llm_tier: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    # Relationships
    workflow: Mapped[Optional["Workflow"]] = relationship(back_populates="audit_logs")

    __table_args__ = (
        Index("idx_audit_workflow", "workflow_id"),
        Index("idx_audit_created", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog {self.id} agent={self.agent_name} action={self.action}>"


# ── Agent Health ─────────────────────────────────────────────────────────────

class AgentHealth(Base):
    __tablename__ = "agent_health"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    avg_latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_rate: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    def __repr__(self) -> str:
        return f"<AgentHealth {self.agent_name} status={self.status}>"


# ── Failed Triggers (Dead Letter Queue) ──────────────────────────────────────

class FailedTrigger(Base):
    __tablename__ = "failed_triggers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    error: Mapped[str] = mapped_column(Text, nullable=False)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    can_replay: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    replayed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index(
            "idx_failed_triggers_replay", "can_replay",
            postgresql_where=(can_replay.is_(True)),
        ),
    )

    def __repr__(self) -> str:
        return f"<FailedTrigger {self.id} source={self.source} can_replay={self.can_replay}>"
