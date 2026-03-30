"""Approval Management API — Human-in-the-loop workflow approvals.

Endpoints:
- POST /approvals/{workflow_id}/approve — Approve a pending workflow
- POST /approvals/{workflow_id}/reject — Reject a pending workflow
- GET /approvals/pending — List all pending approvals
- GET /approvals/{workflow_id} — Get approval status for workflow
- POST /approvals/{workflow_id}/delegate — Delegate approval to another user
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.database import get_db
from nexus.tools.registry import ToolRegistry

logger = structlog.get_logger()
router = APIRouter(prefix="/approvals", tags=["approvals"])


# ── Request/Response Schemas ─────────────────────────────────────────────────


class ApprovalAction(BaseModel):
    approver: str = Field(..., description="User ID or email of approver")
    comments: str | None = Field(None, description="Optional approval comments")
    delegation_reason: str | None = Field(None, description="Reason for delegation")


class ApprovalResponse(BaseModel):
    workflow_id: str
    approval_id: str | None
    status: str  # approved, rejected, pending, delegated
    approver: str | None
    comments: str | None
    decided_at: datetime | None
    next_action: str | None


class PendingApproval(BaseModel):
    workflow_id: str
    workflow_type: str
    approver_role: str
    amount: float | None
    requestor: str | None
    requested_at: datetime
    waiting_since_hours: float


# ── Helper Functions ─────────────────────────────────────────────────────────


async def get_workflow_approval_info(
    workflow_id: str,
    db: AsyncSession,
) -> dict[str, Any] | None:
    """Get workflow and its approval status."""
    result = await db.execute(
        text("SELECT * FROM workflows WHERE id = :id"),
        {"id": workflow_id},
    )
    workflow = result.mappings().first()
    if not workflow:
        return None

    # Get existing approvals
    result = await db.execute(
        text(
            "SELECT * FROM approvals WHERE workflow_id = :id ORDER BY requested_at DESC"
        ),
        {"id": workflow_id},
    )
    approvals = result.mappings().all()

    return {
        "workflow": dict(workflow),
        "approvals": [dict(a) for a in approvals],
    }


async def notify_approval_decision(
    workflow: dict,
    action: str,  # "approved" or "rejected"
    approver: str,
    comments: str | None,
    tools: ToolRegistry,
) -> None:
    """Send Slack/Email notification about approval decision."""
    wf_type = workflow.get("workflow_type", "workflow")
    wf_id = workflow.get("id", "unknown")

    # Slack notification
    if tools.has("slack_messenger"):
        slack = tools.get("slack_messenger")
        emoji = "✅" if action == "approved" else "❌"
        await slack.call({
            "action": "send_message",
            "channel": "#workflow-approvals",
            "text": (
                f"{emoji} {action.title()} — {wf_type.title()} Workflow\n"
                f"ID: `{wf_id}`\n"
                f"Approver: {approver}"
                + (f"\nComments: {comments}" if comments else "")
            ),
        })

    # Email notification
    if tools.has("email_connector"):
        email = tools.get("email_connector")
        # Notify requestor
        created_by = workflow.get("created_by")
        if created_by and "@" in created_by:
            await email.call({
                "action": "send_notification",
                "to": created_by,
                "subject": f"Workflow {action.title()}: {wf_type} ({wf_id[:8]}...)",
                "message": (
                    f"Your {wf_type} workflow has been {action}.\n\n"
                    f"Workflow ID: {wf_id}\n"
                    f"Approver: {approver}"
                    + (f"\nComments: {comments}" if comments else "")
                ),
            })


# ── API Endpoints ────────────────────────────────────────────────────────────


@router.get("/pending", response_model=list[PendingApproval])
async def list_pending_approvals(
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
):
    """List all workflows awaiting approval."""
    result = await db.execute(
        text("""
            SELECT w.id, w.workflow_type, w.created_at, w.payload,
                   a.approver, a.requested_at
            FROM workflows w
            JOIN approvals a ON w.id = a.workflow_id
            WHERE w.status = 'awaiting_approval'
              AND a.status = 'pending'
            ORDER BY a.requested_at ASC
            LIMIT :limit
        """),
        {"limit": limit},
    )
    rows = result.mappings().all()

    now = datetime.now(timezone.utc)
    pending = []
    for row in rows:
        requested = row["requested_at"]
        if requested.tzinfo is None:
            requested = requested.replace(tzinfo=timezone.utc)
        waiting_hours = (now - requested).total_seconds() / 3600

        # Extract amount from payload if available
        payload = row.get("payload", {})
        amount = None
        if isinstance(payload, str):
            import json
            try:
                payload = json.loads(payload)
            except Exception:
                pass
        if isinstance(payload, dict):
            amount = payload.get("amount") or payload.get("total_budget") or payload.get("unit_price", 0) * payload.get("quantity", 1)

        pending.append(PendingApproval(
            workflow_id=str(row["id"]),
            workflow_type=row["workflow_type"],
            approver_role=row["approver"],
            amount=amount,
            requestor=row.get("created_by"),
            requested_at=row["requested_at"],
            waiting_since_hours=round(waiting_hours, 2),
        ))

    return pending


@router.get("/{workflow_id}", response_model=dict)
async def get_approval_status(
    workflow_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get approval status for a specific workflow."""
    info = await get_workflow_approval_info(workflow_id, db)
    if not info:
        raise HTTPException(status_code=404, detail="Workflow not found")

    workflow = info["workflow"]
    approvals = info["approvals"]

    # Determine current status
    if workflow["status"] == "completed":
        status = "approved"
    elif workflow["status"] == "failed":
        status = "rejected"
    elif workflow["status"] == "awaiting_approval":
        status = "pending"
    else:
        status = workflow["status"]

    # Find latest approval
    latest_approval = approvals[0] if approvals else None

    return {
        "workflow_id": workflow_id,
        "workflow_type": workflow["workflow_type"],
        "workflow_status": workflow["status"],
        "approval_status": status,
        "pending_approvals": [
            {
                "approver": a["approver"],
                "requested_at": a["requested_at"].isoformat(),
            }
            for a in approvals
            if a["status"] == "pending"
        ],
        "decided_approvals": [
            {
                "approver": a["approver"],
                "status": a["status"],
                "comments": a["comments"],
                "decided_at": a["decided_at"].isoformat() if a["decided_at"] else None,
            }
            for a in approvals
            if a["status"] in ("approved", "rejected")
        ],
    }


@router.post("/{workflow_id}/approve", response_model=ApprovalResponse)
async def approve_workflow(
    workflow_id: str,
    action: ApprovalAction,
    db: AsyncSession = Depends(get_db),
):
    """Approve a pending workflow."""
    info = await get_workflow_approval_info(workflow_id, db)
    if not info:
        raise HTTPException(status_code=404, detail="Workflow not found")

    workflow = info["workflow"]

    if workflow["status"] != "awaiting_approval":
        raise HTTPException(
            status_code=400,
            detail=f"Workflow is not awaiting approval (status: {workflow['status']})",
        )

    now = datetime.now(timezone.utc)

    # Record approval decision
    await db.execute(
        text("""
            UPDATE approvals
            SET status = 'approved',
                comments = :comments,
                decided_at = :decided_at
            WHERE workflow_id = :workflow_id
              AND status = 'pending'
        """),
        {
            "comments": action.comments,
            "decided_at": now,
            "workflow_id": workflow_id,
        },
    )

    # Update workflow status
    await db.execute(
        text("""
            UPDATE workflows
            SET status = 'in_progress',
                updated_at = :updated_at
            WHERE id = :id
        """),
        {"updated_at": now, "id": workflow_id},
    )

    await db.commit()

    # Send notifications
    tools = ToolRegistry.from_settings()
    try:
        await notify_approval_decision(
            workflow, "approved", action.approver, action.comments, tools
        )
    finally:
        await tools.close_all()

    logger.info(
        "workflow_approved",
        workflow_id=workflow_id,
        approver=action.approver,
    )

    return ApprovalResponse(
        workflow_id=workflow_id,
        approval_id=None,
        status="approved",
        approver=action.approver,
        comments=action.comments,
        decided_at=now,
        next_action="Workflow resumed for execution",
    )


@router.post("/{workflow_id}/reject", response_model=ApprovalResponse)
async def reject_workflow(
    workflow_id: str,
    action: ApprovalAction,
    db: AsyncSession = Depends(get_db),
):
    """Reject a pending workflow."""
    info = await get_workflow_approval_info(workflow_id, db)
    if not info:
        raise HTTPException(status_code=404, detail="Workflow not found")

    workflow = info["workflow"]

    if workflow["status"] != "awaiting_approval":
        raise HTTPException(
            status_code=400,
            detail=f"Workflow is not awaiting approval (status: {workflow['status']})",
        )

    now = datetime.now(timezone.utc)

    # Record rejection
    await db.execute(
        text("""
            UPDATE approvals
            SET status = 'rejected',
                comments = :comments,
                decided_at = :decided_at
            WHERE workflow_id = :workflow_id
              AND status = 'pending'
        """),
        {
            "comments": action.comments,
            "decided_at": now,
            "workflow_id": workflow_id,
        },
    )

    # Update workflow status to failed
    await db.execute(
        text("""
            UPDATE workflows
            SET status = 'failed',
                updated_at = :updated_at,
                completed_at = :completed_at
            WHERE id = :id
        """),
        {"updated_at": now, "completed_at": now, "id": workflow_id},
    )

    await db.commit()

    # Send notifications
    tools = ToolRegistry.from_settings()
    try:
        await notify_approval_decision(
            workflow, "rejected", action.approver, action.comments, tools
        )
    finally:
        await tools.close_all()

    logger.info(
        "workflow_rejected",
        workflow_id=workflow_id,
        approver=action.approver,
        comments=action.comments,
    )

    return ApprovalResponse(
        workflow_id=workflow_id,
        approval_id=None,
        status="rejected",
        approver=action.approver,
        comments=action.comments,
        decided_at=now,
        next_action="Workflow terminated - resubmit if needed",
    )


@router.post("/{workflow_id}/delegate", response_model=ApprovalResponse)
async def delegate_approval(
    workflow_id: str,
    action: ApprovalAction,
    db: AsyncSession = Depends(get_db),
):
    """Delegate approval to another user."""
    info = await get_workflow_approval_info(workflow_id, db)
    if not info:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if not action.delegation_reason:
        raise HTTPException(
            status_code=400, detail="delegation_reason is required"
        )

    now = datetime.now(timezone.utc)

    # Update existing pending approval with delegation note
    await db.execute(
        text("""
            UPDATE approvals
            SET comments = COALESCE(comments, '') || :delegation_note,
                approver = :new_approver
            WHERE workflow_id = :workflow_id
              AND status = 'pending'
        """),
        {
            "delegation_note": f"[Delegated by {action.approver}: {action.delegation_reason}]",
            "new_approver": action.approver,
            "workflow_id": workflow_id,
        },
    )

    await db.commit()

    # Send notification to new approver
    tools = ToolRegistry.from_settings()
    try:
        if tools.has("slack_messenger"):
            slack = tools.get("slack_messenger")
            await slack.call({
                "action": "send_message",
                "channel": f"@{action.approver}",
                "text": (
                    f"📋 Approval Delegated to You\n"
                    f"Workflow: {workflow_id[:8]}... ({info['workflow']['workflow_type']})\n"
                    f"Delegated by: {action.approver}\n"
                    f"Reason: {action.delegation_reason}"
                ),
            })
    finally:
        await tools.close_all()

    logger.info(
        "approval_delegated",
        workflow_id=workflow_id,
        from_approver=action.approver,
        reason=action.delegation_reason,
    )

    return ApprovalResponse(
        workflow_id=workflow_id,
        approval_id=None,
        status="delegated",
        approver=action.approver,
        comments=action.delegation_reason,
        decided_at=now,
        next_action=f"Awaiting approval from {action.approver}",
    )
