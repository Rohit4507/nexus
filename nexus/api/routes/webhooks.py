"""Webhook Endpoints for n8n and External Trigger Orchestration.

Endpoints:
- POST /webhooks/n8n — Generic n8n webhook trigger
- POST /webhooks/slack — Slack slash command / message trigger
- POST /webhooks/email — Email-triggered workflows (via webhook)
- GET /webhooks/status — Webhook delivery status

All webhooks support idempotency via X-Idempotency-Key header.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy import text

from nexus.database import get_db
from nexus.agents.orchestrator import run_workflow
from nexus.memory.audit_logger import AuditLogger

logger = structlog.get_logger()
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# ── Helper Functions ─────────────────────────────────────────────────────────


async def check_idempotency(
    db,
    idempotency_key: str,
) -> dict | None:
    """Check if request with this idempotency key was already processed."""
    if not idempotency_key:
        return None

    result = await db.execute(
        text("""
            SELECT id, status, payload FROM workflows
            WHERE payload_hash = :hash
            ORDER BY created_at DESC
            LIMIT 1
        """),
        {"hash": idempotency_key},
    )
    row = result.first()
    if row:
        return {"id": str(row[0]), "status": row[1]}
    return None


def extract_workflow_type_from_payload(payload: dict) -> str:
    """Infer workflow type from payload structure."""
    # Check explicit type field
    if "workflow_type" in payload:
        return payload["workflow_type"]

    # Infer from content
    if "employee_name" in payload or "new_hire" in payload:
        return "onboarding"
    if "item" in payload or "purchase" in payload or "po" in payload:
        return "procurement"
    if "contract_type" in payload or "agreement" in payload or "nda" in payload:
        return "contract"
    if "meeting_title" in payload or "transcript" in payload:
        return "meeting"

    # Default to procurement
    return "procurement"


# ── Webhook Endpoints ────────────────────────────────────────────────────────


@router.post("/n8n")
async def n8n_webhook(
    request: Request,
    x_idempotency_key: str | None = Header(None, alias="X-Idempotency-Key"),
    db=Depends(get_db),
):
    """Generic n8n webhook trigger.

    Expects JSON payload with:
    {
        "workflow_type": "procurement|onboarding|contract|meeting",
        "payload": {...},
        "created_by": "user@example.com"  # optional
    }

    Or minimal payload that will be auto-classified:
    {
        "message": "Need to order 5 laptops",
        "channel": "#requests"
    }
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Check idempotency
    if x_idempotency_key:
        existing = await check_idempotency(db, x_idempotency_key)
        if existing:
            logger.info("webhook_duplicate", key=x_idempotency_key)
            return {
                "status": "duplicate",
                "workflow_id": existing["id"],
                "previous_status": existing["status"],
            }

    # Extract workflow type
    workflow_type = body.get("workflow_type")
    if not workflow_type:
        workflow_type = extract_workflow_type_from_payload(body)

    # Validate workflow type
    valid_types = {"procurement", "onboarding", "contract", "meeting"}
    if workflow_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid workflow_type. Must be one of: {list(valid_types)}",
        )

    # Compute payload hash for idempotency
    payload_json = json.dumps(body.get("payload", body), sort_keys=True)
    payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()

    # Create workflow record
    import uuid
    workflow_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    await db.execute(
        text("""
            INSERT INTO workflows (id, workflow_type, status, payload,
                                   payload_hash, created_by, created_at, updated_at)
            VALUES (:id, :type, :status, :payload, :hash, :by, :at, :at)
        """),
        {
            "id": workflow_id,
            "type": workflow_type,
            "status": "pending",
            "payload": payload_json,
            "hash": x_idempotency_key or payload_hash,
            "by": body.get("created_by"),
            "at": now,
        },
    )
    await db.commit()

    # Audit log
    audit = AuditLogger(db)
    await audit.log_action(
        workflow_id=workflow_id,
        agent_name="webhook",
        action="n8n_trigger",
        status="success",
        input_data={"workflow_type": workflow_type, "source": "n8n"},
    )

    # Run workflow
    try:
        result = await run_workflow(
            workflow_type=workflow_type,
            payload=body.get("payload", body),
            created_by=body.get("created_by"),
        )

        # Update status
        await db.execute(
            text("""
                UPDATE workflows
                SET status = :status, updated_at = :at
                WHERE id = :id
            """),
            {
                "status": result.get("status", "completed"),
                "at": datetime.now(timezone.utc),
                "id": workflow_id,
            },
        )
        await db.commit()

        return {
            "workflow_id": workflow_id,
            "status": result.get("status"),
            "phases_completed": len(result.get("agent_outputs", [])),
            "idempotency_key": x_idempotency_key or payload_hash,
        }

    except Exception as e:
        logger.error("webhook_workflow_failed", workflow_id=workflow_id, error=str(e))
        await db.execute(
            text("""
                UPDATE workflows SET status = 'failed', updated_at = :at
                WHERE id = :id
            """),
            {"at": datetime.now(timezone.utc), "id": workflow_id},
        )
        await db.commit()

        raise HTTPException(status_code=500, detail=f"Workflow failed: {str(e)}")


@router.post("/slack")
async def slack_webhook(
    request: Request,
    db=Depends(get_db),
):
    """Slack slash command / message event webhook.

    Handles:
    - Slash commands: /nexus order 5 laptops
    - Message events: @nexus-bot New hire starting Monday

    Slack sends form-encoded data for slash commands.
    """
    content_type = request.headers.get("content-type", "")

    if "application/x-www-form-urlencoded" in content_type:
        # Slash command
        form_data = await request.form()
        text = form_data.get("text", "")
        channel = form_data.get("channel_id", "")
        user = form_data.get("user_id", "")
        response_url = form_data.get("response_url")
    else:
        # Message event (JSON)
        try:
            body = await request.json()
            event = body.get("event", {})
            text = event.get("text", "")
            channel = event.get("channel", "")
            user = event.get("user", "")
            response_url = None
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid Slack payload")

    if not text.strip():
        return {"text": "Please provide a request. Example: 'order 5 laptops'"}

    # Create workflow payload
    payload = {
        "request_text": text,
        "source": "slack",
        "channel": channel,
        "user": user,
    }

    # Infer workflow type from text
    text_lower = text.lower()
    if "new hire" in text_lower or "onboard" in text_lower or "starting" in text_lower:
        workflow_type = "onboarding"
    elif "order" in text_lower or "purchase" in text_lower or "buy" in text_lower:
        workflow_type = "procurement"
    elif "contract" in text_lower or "agreement" in text_lower or "nda" in text_lower:
        workflow_type = "contract"
    elif "meeting" in text_lower or "schedule" in text_lower:
        workflow_type = "meeting"
    else:
        workflow_type = "procurement"  # default

    # Create workflow record
    import uuid
    workflow_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    payload_json = json.dumps(payload, sort_keys=True)
    payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()

    await db.execute(
        text("""
            INSERT INTO workflows (id, workflow_type, status, payload,
                                   payload_hash, created_by, created_at, updated_at)
            VALUES (:id, :type, :status, :payload, :hash, :by, :at, :at)
        """),
        {
            "id": workflow_id,
            "type": workflow_type,
            "status": "pending",
            "payload": payload_json,
            "hash": payload_hash,
            "by": user,
            "at": now,
        },
    )
    await db.commit()

    # Audit
    audit = AuditLogger(db)
    await audit.log_action(
        workflow_id=workflow_id,
        agent_name="webhook",
        action="slack_trigger",
        status="success",
        input_data={"workflow_type": workflow_type, "channel": channel},
    )

    # Run workflow async (don't wait for response)
    async def run_async():
        try:
            result = await run_workflow(
                workflow_type=workflow_type,
                payload=payload,
                created_by=user,
            )
            # Update status
            async with db() as session:
                await session.execute(
                    text("""
                        UPDATE workflows SET status = :status, updated_at = :at
                        WHERE id = :id
                    """),
                    {
                        "status": result.get("status"),
                        "at": datetime.now(timezone.utc),
                        "id": workflow_id,
                    },
                )
                await session.commit()

            # Respond to Slack if response_url provided
            if response_url:
                import httpx
                status_emoji = {
                    "completed": "✅",
                    "in_progress": "🔄",
                    "failed": "❌",
                    "escalated": "⚠️",
                }.get(result.get("status"), "📋")

                async with httpx.AsyncClient(timeout=10) as client:
                    await client.post(
                        response_url,
                        json={
                            "text": (
                                f"{status_emoji} Workflow {workflow_id[:8]}... "
                                f"{result.get('status', 'started')}"
                            ),
                        },
                    )
        except Exception as e:
            logger.error("slack_workflow_failed", workflow_id=workflow_id, error=str(e))

    # Start async execution
    import asyncio
    asyncio.create_task(run_async())

    # Immediate response to Slack
    return {
        "text": (
            f"📋 Processing your request: \"{text}\"\n"
            f"Workflow ID: `{workflow_id[:8]}...`\n"
            f"Type: {workflow_type}\n"
            f"You'll be notified when complete."
        ),
    }


@router.post("/email")
async def email_webhook(
    request: Request,
    db=Depends(get_db),
):
    """Email-triggered workflows via webhook (e.g., Zapier/Make email parsing).

    Expects JSON:
    {
        "from": "user@example.com",
        "subject": "Purchase Request: 5 Laptops",
        "body": "I need to order 5 Dell laptops for the new sales team...",
        "to": "workflows@company.com"
    }
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    from_email = body.get("from", "unknown")
    subject = body.get("subject", "")
    email_body = body.get("body", "")

    # Combine subject and body for processing
    request_text = f"{subject}\n\n{email_body}"

    # Infer workflow type
    subject_lower = subject.lower()
    if "purchase" in subject_lower or "order" in subject_lower:
        workflow_type = "procurement"
    elif "onboard" in subject_lower or "new hire" in subject_lower:
        workflow_type = "onboarding"
    elif "contract" in subject_lower or "legal" in subject_lower:
        workflow_type = "contract"
    else:
        workflow_type = "procurement"

    payload = {
        "request_text": request_text,
        "source": "email",
        "from": from_email,
    }

    # Create workflow record
    import uuid
    workflow_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    payload_json = json.dumps(payload, sort_keys=True)
    payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()

    await db.execute(
        text("""
            INSERT INTO workflows (id, workflow_type, status, payload,
                                   payload_hash, created_by, created_at, updated_at)
            VALUES (:id, :type, :status, :payload, :hash, :by, :at, :at)
        """),
        {
            "id": workflow_id,
            "type": workflow_type,
            "status": "pending",
            "payload": payload_json,
            "hash": payload_hash,
            "by": from_email,
            "at": now,
        },
    )
    await db.commit()

    # Run workflow
    try:
        result = await run_workflow(
            workflow_type=workflow_type,
            payload=payload,
            created_by=from_email,
        )

        return {
            "workflow_id": workflow_id,
            "status": result.get("status"),
            "message": "Email workflow processed successfully",
        }

    except Exception as e:
        logger.error("email_workflow_failed", workflow_id=workflow_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Workflow failed: {str(e)}")


@router.get("/status/{webhook_id}")
async def get_webhook_status(
    webhook_id: str,
    db=Depends(get_db),
):
    """Get status of a workflow triggered by webhook."""
    result = await db.execute(
        text("SELECT * FROM workflows WHERE id = :id"),
        {"id": webhook_id},
    )
    row = result.mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="Workflow not found")

    return dict(row)


@router.get("/status")
async def list_webhook_statuses(
    limit: int = 20,
    db=Depends(get_db),
):
    """List recent webhook-triggered workflows."""
    result = await db.execute(
        text("""
            SELECT * FROM workflows
            WHERE payload_hash IS NOT NULL
            ORDER BY created_at DESC
            LIMIT :limit
        """),
        {"limit": limit},
    )
    rows = result.mappings().all()
    return [dict(r) for r in rows]
