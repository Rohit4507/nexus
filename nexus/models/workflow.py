"""Core workflow models: workflows, approvals, sla_events."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    Index,
    Integer,
    String,
    Text,
    ForeignKey,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nexus.database import Base


# ── Enums ────────────────────────────────────────────────────────────────────

WORKFLOW_TYPES = ("procurement", "onboarding", "contract", "meeting")
WORKFLOW_STATUSES = (
    "pending",
    "in_progress",
    "awaiting_approval",
    "completed",
    "failed",
    "escalated",
)
APPROVAL_STATUSES = ("pending", "approved", "rejected")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Workflow ─────────────────────────────────────────────────────────────────

class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workflow_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending"
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    payload_hash: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    sla_deadline: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    approvals: Mapped[list["Approval"]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan"
    )
    sla_events: Mapped[list["SLAEvent"]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[list] = relationship(
        "AuditLog", back_populates="workflow", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_workflows_status", "status"),
        Index("idx_workflows_type", "workflow_type"),
        Index("idx_workflows_hash", "payload_hash"),
    )

    def __repr__(self) -> str:
        return f"<Workflow {self.id} type={self.workflow_type} status={self.status}>"


# ── Approval ─────────────────────────────────────────────────────────────────

class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id"), nullable=False
    )
    approver: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), default="pending"
    )
    comments: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    workflow: Mapped["Workflow"] = relationship(back_populates="approvals")

    __table_args__ = (
        Index(
            "idx_approvals_pending", "status",
            postgresql_where=(status == "pending"),
        ),
    )

    def __repr__(self) -> str:
        return f"<Approval {self.id} approver={self.approver} status={self.status}>"


# ── SLA Event ────────────────────────────────────────────────────────────────

class SLAEvent(Base):
    __tablename__ = "sla_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id"), nullable=False
    )
    phase: Mapped[str] = mapped_column(String(100), nullable=False)
    expected_by: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    breached: Mapped[bool] = mapped_column(Boolean, default=False)
    escalated_to: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    # Relationships
    workflow: Mapped["Workflow"] = relationship(back_populates="sla_events")

    __table_args__ = (
        Index(
            "idx_sla_breached", "breached",
            postgresql_where=(breached.is_(True)),
        ),
    )

    def __repr__(self) -> str:
        return f"<SLAEvent wf={self.workflow_id} phase={self.phase} breached={self.breached}>"
