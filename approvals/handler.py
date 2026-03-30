"""Approval Handler — Create and manage approval requests.

This module provides utilities for:
1. Creating approval records in the database
2. Sending approval requests via Slack and Email
3. Tracking approval status and timeouts
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.memory.audit_logger import AuditLogger
from nexus.tools.registry import ToolRegistry

logger = structlog.get_logger()


# ── Approval Configuration ──────────────────────────────────────────────────

APPROVAL_CHANNELS = {
    "manager": "#manager-approvals",
    "vp": "#vp-approvals",
    "legal": "#legal-review",
    "finance": "#finance-approvals",
}

APPROVAL_EMAILS = {
    "manager": "manager@company.com",
    "vp": "vp@company.com",
    "legal": "legal@company.com",
    "finance": "finance@company.com",
}


class ApprovalHandler:
    """Handles approval request creation and notification."""

    def __init__(
        self,
        db_session: AsyncSession,
        tool_registry: ToolRegistry,
        audit_logger: AuditLogger | None = None,
    ):
        self.db = db_session
        self.tools = tool_registry
        self.audit = audit_logger or AuditLogger(db_session)

    async def create_approval_request(
        self,
        workflow_id: str,
        workflow_type: str,
        approver_role: str,
        amount: float | None = None,
        requestor: str | None = None,
        message: str | None = None,
        payload: dict | None = None,
    ) -> dict[str, Any]:
        """Create an approval request and send notifications.

        Args:
            workflow_id: UUID of the workflow
            workflow_type: procurement, contract, etc.
            approver_role: manager, vp, legal, finance
            amount: Dollar amount requiring approval
            requestor: Person who initiated the request
            message: Custom message for approver
            payload: Full workflow payload for context

        Returns:
            Dict with approval_id, status, and notification results
        """
        # Step 1: Create approval record in database
        approval_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        await self.db.execute(
            text("""
                INSERT INTO approvals (id, workflow_id, approver, status, requested_at)
                VALUES (:id, :workflow_id, :approver, 'pending', :requested_at)
            """),
            {
                "id": approval_id,
                "workflow_id": workflow_id,
                "approver": approver_role,
                "requested_at": now,
            },
        )

        # Update workflow status
        await self.db.execute(
            text("""
                UPDATE workflows
                SET status = 'awaiting_approval',
                    updated_at = :updated_at
                WHERE id = :workflow_id
            """),
            {"updated_at": now, "workflow_id": workflow_id},
        )

        await self.db.commit()

        # Step 2: Send notifications
        notification_result = await self._send_notifications(
            workflow_id=workflow_id,
            workflow_type=workflow_type,
            approver_role=approver_role,
            amount=amount,
            requestor=requestor,
            message=message,
            payload=payload,
        )

        # Step 3: Audit log
        if self.audit:
            await self.audit.log_action(
                workflow_id=workflow_id,
                agent_name="approval_handler",
                action="create_approval_request",
                status="success",
                input_data={
                    "approver_role": approver_role,
                    "amount": amount,
                    "requestor": requestor,
                },
                output_data={
                    "approval_id": str(approval_id),
                    "notifications": notification_result,
                },
            )

        logger.info(
            "approval_request_created",
            workflow_id=workflow_id,
            approval_id=approval_id,
            approver=approver_role,
        )

        return {
            "approval_id": str(approval_id),
            "workflow_id": workflow_id,
            "approver_role": approver_role,
            "status": "pending",
            "created_at": now.isoformat(),
            "notifications": notification_result,
        }

    async def _send_notifications(
        self,
        workflow_id: str,
        workflow_type: str,
        approver_role: str,
        amount: float | None,
        requestor: str | None,
        message: str | None,
        payload: dict | None,
    ) -> dict[str, Any]:
        """Send approval notifications via Slack and Email."""
        result = {"slack": None, "email": None}

        # Build approval message
        amount_str = f"${amount:,.2f}" if amount else "N/A"
        base_message = (
            f"*Approval Required*\n\n"
            f"*Workflow ID:* `{workflow_id[:8]}...`\n"
            f"*Type:* {workflow_type.upper()}\n"
            f"*Amount:* {amount_str}\n"
            f"*Requestor:* {requestor or 'Unknown'}\n\n"
        )
        if message:
            base_message += f"*Details:* {message}\n\n"
        base_message += "_Click 'Approve' or 'Reject' to decide._"

        # ── Slack Notification ──────────────────────────────────
        if self.tools.has("slack_messenger"):
            try:
                slack = self.tools.get("slack_messenger")
                channel = APPROVAL_CHANNELS.get(
                    approver_role,
                    f"#approvals-{approver_role}",
                )

                slack_result = await slack.call({
                    "action": "send_approval",
                    "workflow_id": workflow_id,
                    "workflow_type": workflow_type,
                    "message": base_message,
                    "amount": amount or 0,
                    "requestor": requestor or "Unknown",
                    "channel": channel,
                })
                result["slack"] = {
                    "status": "sent",
                    "channel": channel,
                    "ts": slack_result.get("ts"),
                }
            except Exception as e:
                logger.warning("slack_approval_failed", error=str(e))
                result["slack"] = {"status": "failed", "error": str(e)}

        # ── Email Notification ──────────────────────────────────
        if self.tools.has("email_connector"):
            try:
                email = self.tools.get("email_connector")
                to_email = APPROVAL_EMAILS.get(
                    approver_role,
                    f"{approver_role}@company.com",
                )

                subject = f"[{workflow_type.upper()}] Approval Required: {amount_str}"

                email_body = (
                    f"Dear {approver_role.title()},\n\n"
                    f"A {workflow_type} request requires your approval.\n\n"
                    f"Workflow ID: {workflow_id}\n"
                    f"Amount: {amount_str}\n"
                    f"Requestor: {requestor or 'Unknown'}\n\n"
                )
                if message:
                    email_body += f"Details: {message}\n\n"

                email_body += (
                    "To approve or reject this request, please:\n"
                    "1. Visit the NEXUS Dashboard\n"
                    "2. Navigate to Pending Approvals\n"
                    "3. Select this workflow and make your decision\n\n"
                    "Alternatively, reply to this email with 'APPROVE' or 'REJECT' "
                    "followed by any comments.\n\n"
                    "---\nNEXUS Enterprise Agentic AI Platform"
                )

                email_result = await email.call({
                    "action": "send_approval_email",
                    "to": to_email,
                    "workflow_id": workflow_id,
                    "workflow_type": workflow_type,
                    "subject": subject,
                    "message": email_body,
                    "amount": amount or 0,
                })
                result["email"] = {
                    "status": "sent",
                    "to": to_email,
                }
            except Exception as e:
                logger.warning("email_approval_failed", error=str(e))
                result["email"] = {"status": "failed", "error": str(e)}

        return result

    async def get_pending_approvals(self, limit: int = 50) -> list[dict]:
        """Get all pending approvals."""
        result = await self.db.execute(
            text("""
                SELECT w.id, w.workflow_type, w.payload, w.created_at,
                       a.approver, a.requested_at
                FROM workflows w
                JOIN approvals a ON w.id = a.workflow_id
                WHERE a.status = 'pending'
                ORDER BY a.requested_at ASC
                LIMIT :limit
            """),
            {"limit": limit},
        )
        rows = result.mappings().all()
        return [dict(row) for row in rows]

    async def approve(
        self,
        workflow_id: str,
        approver: str,
        comments: str | None = None,
    ) -> bool:
        """Mark an approval as approved."""
        return await self._update_approval(
            workflow_id=workflow_id,
            approver=approver,
            decision="approve",
            comments=comments,
        )

    async def reject(
        self,
        workflow_id: str,
        approver: str,
        comments: str | None = None,
    ) -> bool:
        """Mark an approval as rejected."""
        return await self._update_approval(
            workflow_id=workflow_id,
            approver=approver,
            decision="reject",
            comments=comments,
        )

    async def _update_approval(
        self,
        workflow_id: str,
        approver: str,
        decision: Literal["approve", "reject"],
        comments: str | None = None,
    ) -> bool:
        """Internal: Update approval record and workflow status."""
        now = datetime.now(timezone.utc)

        # Update approval record
        result = await self.db.execute(
            text("""
                UPDATE approvals
                SET status = :decision,
                    decided_at = :decided_at,
                    comments = :comments
                WHERE workflow_id = :workflow_id
                  AND status = 'pending'
            """),
            {
                "decision": decision,
                "decided_at": now,
                "comments": comments,
                "workflow_id": workflow_id,
            },
        )

        if result.rowcount == 0:
            logger.warning("no_pending_approval_found", workflow_id=workflow_id)
            return False

        # Update workflow status
        new_status = "in_progress" if decision == "approve" else "failed"
        await self.db.execute(
            text("""
                UPDATE workflows
                SET status = :status,
                    updated_at = :updated_at
                WHERE id = :workflow_id
            """),
            {"status": new_status, "updated_at": now, "workflow_id": workflow_id},
        )

        await self.db.commit()

        # Audit log
        if self.audit:
            await self.audit.log_action(
                workflow_id=workflow_id,
                agent_name="approval_handler",
                action=f"decision_{decision}",
                status="success",
                input_data={"approver": approver, "comments": comments},
                output_data={"new_status": new_status},
            )

        logger.info(
            "approval_decision_recorded",
            workflow_id=workflow_id,
            decision=decision,
            approver=approver,
        )

        return True


# ── Convenience Function ─────────────────────────────────────────────────────

async def create_approval_request(
    db_session: AsyncSession,
    tool_registry: ToolRegistry,
    workflow_id: str,
    workflow_type: str,
    approver_role: str,
    amount: float | None = None,
    requestor: str | None = None,
    message: str | None = None,
    payload: dict | None = None,
) -> dict[str, Any]:
    """Convenience function to create an approval request.

    Usage:
        result = await create_approval_request(
            db, tools,
            workflow_id="abc-123",
            workflow_type="procurement",
            approver_role="manager",
            amount=15000,
            requestor="alice@company.com",
        )
    """
    handler = ApprovalHandler(db_session, tool_registry)
    return await handler.create_approval_request(
        workflow_id=workflow_id,
        workflow_type=workflow_type,
        approver_role=approver_role,
        amount=amount,
        requestor=requestor,
        message=message,
        payload=payload,
    )
