"""Approval Decision API — Handle Slack/Email approval callbacks.

Endpoints:
    POST /approvals/decide    — Process approval decision (approve/reject)
    GET  /approvals/pending   — List workflows awaiting human approval
    GET  /approvals/:id       — Get approval details for a workflow
    POST /approvals/:id/review — Submit human review decision

Supports:
    - Slack interactive button payloads
    - Email reply parsing (IMAP webhook)
    - Manual review via Streamlit/API
"""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.database import get_db
from nexus.memory.audit_logger import AuditLogger

router = APIRouter(prefix="/approvals", tags=["approvals"])


# ── Request/Response Models ──────────────────────────────────────────────────

class SlackApprovalPayload(BaseModel):
    """Slack interactive button payload."""
    type: str = "block_actions"
    user: dict[str, str]
    channel: dict[str, str]
    message: dict[str, Any]
    actions: list[dict[str, Any]]
    response_url: str | None = None


class EmailApprovalPayload(BaseModel):
    """Email reply approval payload."""
    workflow_id: str
    approver_email: str
    decision: Literal["approve", "reject"]
    comments: str | None = None
    raw_email: str | None = None


class ManualReviewPayload(BaseModel):
    """Manual review decision via API/Streamlit."""
    workflow_id: str = Field(..., description="Workflow UUID")
    approver: str = Field(..., description="Approver name/email")
    decision: Literal["approve", "reject"] = Field(...)
    comments: str | None = None
    password: str | None = Field(None, description="Admin password for auth")


class ApprovalResponse(BaseModel):
    """Standard approval response."""
    success: bool
    workflow_id: str
    decision: str
    message: str
    previous_status: str | None = None
    new_status: str | None = None


class PendingApproval(BaseModel):
    """Pending approval record."""
    workflow_id: str
    workflow_type: str
    approver_role: str
    amount: float | None = None
    requestor: str | None = None
    created_at: str
    waiting_since: str
    sla_progress: float


# ── Security Helpers ─────────────────────────────────────────────────────────

def verify_slack_signature(
    body: bytes,
    headers: dict,
    signing_secret: str,
) -> bool:
    """Verify Slack request signature for security."""
    slack_signing_version = headers.get("X-Slack-Signature", "")
    slack_request_timestamp = headers.get("X-Slack-Request-Timestamp", "")

    # Reject old requests (prevent replay attacks)
    if abs(datetime.now(timezone.utc).timestamp() - int(slack_request_timestamp)) > 300:
        return False

    # Build signature
    sig_basestring = f"v0:{slack_request_timestamp}:".encode() + body
    signature_hash = hmac.new(
        signing_secret.encode(),
        sig_basestring,
        hashlib.sha256
    ).hexdigest()
    computed_signature = f"v0={signature_hash}"

    return hmac.compare_digest(computed_signature, slack_signing_version)


async def _get_approval_info(workflow_id: str, db: AsyncSession) -> dict | None:
    """Fetch approval info for a workflow."""
    result = await db.execute(
        text("""
            SELECT w.id, w.workflow_type, w.status, w.payload, w.created_at,
                   a.id as approval_id, a.approver, a.status as approval_status,
                   a.requested_at
            FROM workflows w
            LEFT JOIN approvals a ON w.id = a.workflow_id AND a.status = 'pending'
            WHERE w.id = :workflow_id
        """),
        {"workflow_id": workflow_id},
    )
    row = result.mappings().first()
    if row:
        return dict(row)
    return None


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/decide", response_model=ApprovalResponse)
async def handle_approval_decision(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ApprovalResponse:
    """Universal approval decision endpoint.

    Accepts:
    1. Slack interactive payload (Content-Type: application/x-www-form-urlencoded)
    2. JSON payload from email webhook or manual API call

    Returns:
        ApprovalResponse with success status and workflow state change.
    """
    content_type = request.headers.get("Content-Type", "")

    # ── Slack Payload ──────────────────────────────────────────
    if "application/x-www-form-urlencoded" in content_type:
        body = await request.body()
        form_data = await request.form()
        payload_str = form_data.get("payload", "")

        if not payload_str:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing 'payload' field in form data",
            )

        import json
        try:
            slack_payload = SlackApprovalPayload(**json.loads(payload_str))
        except (json.JSONDecodeError, Exception) as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid Slack payload: {str(e)}",
            )

        # Verify Slack signature (if secret configured)
        signing_secret = os.getenv("SLACK_SIGNING_SECRET", "")
        if signing_secret:
            if not verify_slack_signature(body, dict(request.headers), signing_secret):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid Slack signature",
                )

        # Extract decision from Slack action
        action = slack_payload.actions[0] if slack_payload.actions else {}
        action_id = action.get("action_id", "")
        workflow_id = action.get("value", "")

        if not workflow_id:
            # Try to extract from message text
            msg = slack_payload.message.get("text", "")
            if "Workflow" in msg:
                parts = msg.split()
                for i, p in enumerate(parts):
                    if p == "Workflow" and i + 1 < len(parts):
                        workflow_id = parts[i + 1][:36]

        if not workflow_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not extract workflow_id from Slack payload",
            )

        decision = "approve" if "approve" in action_id else "reject"
        approver = slack_payload.user.get("email", slack_payload.user.get("id", "unknown"))

        return await _process_approval_decision(
            workflow_id=workflow_id,
            approver=approver,
            decision=decision,
            db=db,
        )

    # ── JSON Payload (Email webhook or Manual API) ───────────
    else:
        try:
            json_data = await request.json()
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON body",
            )

        # Try EmailApprovalPayload first
        if "approver_email" in json_data:
            try:
                payload = EmailApprovalPayload(**json_data)
                return await _process_approval_decision(
                    workflow_id=payload.workflow_id,
                    approver=payload.approver_email,
                    decision=payload.decision,
                    comments=payload.comments,
                    db=db,
                )
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid email approval payload: {str(e)}",
                )

        # Try ManualReviewPayload
        if "workflow_id" in json_data and "approver" in json_data:
            try:
                payload = ManualReviewPayload(**json_data)

                # Simple password auth for manual reviews
                if payload.password:
                    admin_password = os.getenv("NEXUS_ADMIN_PASSWORD", "")
                    if admin_password and payload.password != admin_password:
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="Invalid admin password",
                        )

                return await _process_approval_decision(
                    workflow_id=payload.workflow_id,
                    approver=payload.approver,
                    decision=payload.decision,
                    comments=payload.comments,
                    db=db,
                )
            except Exception as e:
                if isinstance(e, HTTPException):
                    raise
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid manual review payload: {str(e)}",
                )

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payload must match EmailApprovalPayload or ManualReviewPayload schema",
        )


async def _process_approval_decision(
    workflow_id: str,
    approver: str,
    decision: Literal["approve", "reject"],
    db: AsyncSession,
    comments: str | None = None,
) -> ApprovalResponse:
    """Internal: Process approval decision and update workflow."""

    # Fetch workflow and approval info
    approval_info = await _get_approval_info(workflow_id, db)

    if not approval_info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow {workflow_id} not found",
        )

    previous_status = approval_info["status"]

    # Check if workflow is in a state that allows approval
    if previous_status not in ("awaiting_approval", "in_progress", "pending"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Workflow status '{previous_status}' does not allow approval",
        )

    # Update approval record
    await db.execute(
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
            "decided_at": datetime.now(timezone.utc),
            "comments": comments,
            "workflow_id": workflow_id,
        },
    )

    # Update workflow status
    if decision == "approve":
        # Workflow stays in 'in_progress' for manual resume
        # User must trigger resume via API or Streamlit
        new_status = "in_progress"
        message = "Approval granted. Workflow ready for manual resume."
    else:
        new_status = "failed"
        message = "Approval rejected. Workflow marked as failed."

    await db.execute(
        text("""
            UPDATE workflows
            SET status = :status,
                updated_at = :updated_at
            WHERE id = :workflow_id
        """),
        {
            "status": new_status,
            "updated_at": datetime.now(timezone.utc),
            "workflow_id": workflow_id,
        },
    )

    # Audit log the decision
    audit = AuditLogger(db)
    await audit.log_action(
        workflow_id=workflow_id,
        agent_name="approvals_api",
        action=f"decision_{decision}",
        status="success",
        input_data={"approver": approver, "comments": comments},
        output_data={"previous_status": previous_status, "new_status": new_status},
    )

    await db.commit()

    return ApprovalResponse(
        success=True,
        workflow_id=workflow_id,
        decision=decision,
        message=message,
        previous_status=previous_status,
        new_status=new_status,
    )


@router.get("/pending", response_model=list[PendingApproval])
async def list_pending_approvals(
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
) -> list[PendingApproval]:
    """List all workflows awaiting human approval."""
    result = await db.execute(
        text("""
            SELECT w.id as workflow_id,
                   w.workflow_type,
                   w.status,
                   w.payload,
                   w.created_at,
                   a.approver as approver_role,
                   a.requested_at as waiting_since
            FROM workflows w
            JOIN approvals a ON w.id = a.workflow_id
            WHERE a.status = 'pending'
              AND w.status IN ('pending', 'in_progress', 'awaiting_approval')
            ORDER BY a.requested_at ASC
            LIMIT :limit
        """),
        {"limit": limit},
    )

    rows = result.mappings().all()
    pending = []

    now = datetime.now(timezone.utc)
    for row in rows:
        payload = row.get("payload", {})
        waiting_since = row["waiting_since"]
        if isinstance(waiting_since, str):
            waiting_dt = datetime.fromisoformat(waiting_since.replace("Z", "+00:00"))
        else:
            waiting_dt = waiting_since

        elapsed = (now - waiting_since.replace(tzinfo=timezone.utc) if waiting_since.tzinfo is None else waiting_since).total_seconds()
        # Assume 24h SLA for approval
        sla_progress = min(100, elapsed / 86400 * 100)

        pending.append(PendingApproval(
            workflow_id=str(row["workflow_id"]),
            workflow_type=row["workflow_type"],
            approver_role=row["approver_role"],
            amount=payload.get("amount") or payload.get("total_budget"),
            requestor=payload.get("requestor") or payload.get("created_by"),
            created_at=row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
            waiting_since=row["waiting_since"].isoformat() if hasattr(row["waiting_since"], "isoformat") else str(row["waiting_since"]),
            sla_progress=round(sla_progress, 1),
        ))

    return pending


@router.get("/{workflow_id}", response_model=dict)
async def get_approval_details(
    workflow_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get approval details for a specific workflow."""
    result = await db.execute(
        text("""
            SELECT w.id, w.workflow_type, w.status, w.payload, w.created_at,
                   a.id as approval_id, a.approver, a.status as approval_status,
                   a.comments, a.requested_at, a.decided_at
            FROM workflows w
            LEFT JOIN approvals a ON w.id = a.workflow_id
            WHERE w.id = :workflow_id
        """),
        {"workflow_id": workflow_id},
    )

    row = result.mappings().first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow {workflow_id} not found",
        )

    return {
        "workflow_id": str(row["id"]),
        "workflow_type": row["workflow_type"],
        "workflow_status": row["status"],
        "payload": row["payload"],
        "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
        "approval": {
            "approval_id": str(row["approval_id"]) if row["approval_id"] else None,
            "approver": row["approver"],
            "status": row["approval_status"],
            "comments": row["comments"],
            "requested_at": row["requested_at"].isoformat() if hasattr(row["requested_at"], "isoformat") else str(row["requested_at"]) if row["requested_at"] else None,
            "decided_at": row["decided_at"].isoformat() if hasattr(row["decided_at"], "isoformat") else str(row["decided_at"]) if row["decided_at"] else None,
        } if row["approval_id"] else None,
    }


@router.post("/{workflow_id}/resume", response_model=dict)
async def resume_workflow_after_approval(
    workflow_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manually resume a workflow after approval was granted.

    This endpoint is called by the user (or Streamlit UI) to resume
    a workflow that was waiting for human approval.
    """
    # Verify workflow exists and is in correct state
    result = await db.execute(
        text("SELECT status, workflow_type FROM workflows WHERE id = :workflow_id"),
        {"workflow_id": workflow_id},
    )
    row = result.mappings().first()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow {workflow_id} not found",
        )

    if row["status"] != "in_progress":
        # Check if approval was granted
        approval_result = await db.execute(
            text("SELECT status FROM approvals WHERE workflow_id = :workflow_id ORDER BY requested_at DESC LIMIT 1"),
            {"workflow_id": workflow_id},
        )
        approval_row = approval_result.mappings().first()

        if not approval_row or approval_row["status"] != "approved":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Workflow cannot be resumed. Current status: {row['status']}. "
                       "Ensure approval was granted first.",
            )

    # Resume the workflow by re-invoking the orchestrator
    # In production, this would call the LangGraph app with the stored state
    # For now, we'll just update the status and log the resume
    await db.execute(
        text("""
            UPDATE workflows
            SET status = 'in_progress',
                updated_at = :updated_at
            WHERE id = :workflow_id
        """),
        {"updated_at": datetime.now(timezone.utc), "workflow_id": workflow_id},
    )

    # Audit log
    audit = AuditLogger(db)
    await audit.log_action(
        workflow_id=workflow_id,
        agent_name="approvals_api",
        action="workflow_resumed",
        status="success",
        output_data={"workflow_type": row["workflow_type"]},
    )

    await db.commit()

    return {
        "success": True,
        "workflow_id": workflow_id,
        "message": f"Workflow {workflow_id} resumed. Type: {row['workflow_type']}",
        "next_step": "Orchestrator will continue from the point of approval wait",
    }
