"""Meeting intelligence models: meetings, meeting_actions."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nexus.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Meeting ──────────────────────────────────────────────────────────────────

class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    transcript: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    labelled_transcript: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    participants: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    recorded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    # Relationships
    actions: Mapped[list["MeetingAction"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Meeting {self.id} title={self.title!r}>"


# ── Meeting Action ───────────────────────────────────────────────────────────

class MeetingAction(Base):
    __tablename__ = "meeting_actions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id"), nullable=False
    )
    action_text: Mapped[str] = mapped_column(Text, nullable=False)
    assignee: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    status: Mapped[str] = mapped_column(String(30), default="pending")
    workflow_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    # Relationships
    meeting: Mapped["Meeting"] = relationship(back_populates="actions")

    def __repr__(self) -> str:
        return f"<MeetingAction {self.id} assignee={self.assignee} status={self.status}>"
