"""Initial schema — all 8 tables

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-03-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


# revision identifiers
revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── workflows ────────────────────────────────────────────
    op.create_table(
        "workflows",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("workflow_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(30), nullable=False,
                  server_default="pending"),
        sa.Column("payload", JSONB, nullable=False, server_default="{}"),
        sa.Column("payload_hash", sa.String(64), nullable=True),
        sa.Column("sla_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_workflows_status", "workflows", ["status"])
    op.create_index("idx_workflows_type", "workflows", ["workflow_type"])
    op.create_index("idx_workflows_hash", "workflows", ["payload_hash"])

    # ── audit_logs ───────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("workflow_id", UUID(as_uuid=True),
                  sa.ForeignKey("workflows.id"), nullable=True),
        sa.Column("agent_name", sa.String(100), nullable=False),
        sa.Column("action", sa.String(200), nullable=False),
        sa.Column("input_data", JSONB, nullable=True),
        sa.Column("output_data", JSONB, nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("llm_tier", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()")),
    )
    op.create_index("idx_audit_workflow", "audit_logs", ["workflow_id"])
    op.create_index("idx_audit_created", "audit_logs", ["created_at"])

    # ── sla_events ───────────────────────────────────────────
    op.create_table(
        "sla_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("workflow_id", UUID(as_uuid=True),
                  sa.ForeignKey("workflows.id"), nullable=False),
        sa.Column("phase", sa.String(100), nullable=False),
        sa.Column("expected_by", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("breached", sa.Boolean, server_default="false"),
        sa.Column("escalated_to", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()")),
    )
    op.create_index(
        "idx_sla_breached", "sla_events", ["breached"],
        postgresql_where=sa.text("breached = TRUE"),
    )

    # ── approvals ────────────────────────────────────────────
    op.create_table(
        "approvals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("workflow_id", UUID(as_uuid=True),
                  sa.ForeignKey("workflows.id"), nullable=False),
        sa.Column("approver", sa.String(100), nullable=False),
        sa.Column("status", sa.String(30), server_default="pending"),
        sa.Column("comments", sa.Text, nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()")),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_approvals_pending", "approvals", ["status"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    # ── agent_health ─────────────────────────────────────────
    op.create_table(
        "agent_health",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("agent_name", sa.String(100), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("avg_latency_ms", sa.Integer, nullable=True),
        sa.Column("error_rate", sa.Numeric(5, 2), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()")),
    )

    # ── meetings ─────────────────────────────────────────────
    op.create_table(
        "meetings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("transcript", sa.Text, nullable=True),
        sa.Column("labelled_transcript", sa.Text, nullable=True),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("participants", JSONB, nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()")),
    )

    # ── meeting_actions ──────────────────────────────────────
    op.create_table(
        "meeting_actions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("meeting_id", UUID(as_uuid=True),
                  sa.ForeignKey("meetings.id"), nullable=False),
        sa.Column("action_text", sa.Text, nullable=False),
        sa.Column("assignee", sa.String(100), nullable=True),
        sa.Column("due_date", sa.Date, nullable=True),
        sa.Column("priority", sa.String(20), server_default="medium"),
        sa.Column("status", sa.String(30), server_default="pending"),
        sa.Column("workflow_id", UUID(as_uuid=True),
                  sa.ForeignKey("workflows.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()")),
    )

    # ── failed_triggers (DLQ) ────────────────────────────────
    op.create_table(
        "failed_triggers",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("error", sa.Text, nullable=False),
        sa.Column("retries", sa.Integer, server_default="0"),
        sa.Column("can_replay", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()")),
        sa.Column("replayed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_failed_triggers_replay", "failed_triggers", ["can_replay"],
        postgresql_where=sa.text("can_replay = TRUE"),
    )


def downgrade() -> None:
    op.drop_table("failed_triggers")
    op.drop_table("meeting_actions")
    op.drop_table("meetings")
    op.drop_table("agent_health")
    op.drop_table("approvals")
    op.drop_table("sla_events")
    op.drop_table("audit_logs")
    op.drop_table("workflows")
