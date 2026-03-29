"""Workflow API routes — trigger, status, and list workflows."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.database import get_db
from nexus.models.schemas import WorkflowCreate, WorkflowResponse
from nexus.agents.orchestrator import run_workflow
from nexus.memory.audit_logger import AuditLogger

logger = structlog.get_logger()
router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.post("/trigger", response_model=dict)
async def trigger_workflow(
    request: WorkflowCreate,
    db: AsyncSession = Depends(get_db),
):
    """Trigger a new workflow through the orchestrator.

    1. Compute payload hash for idempotency
    2. Check for duplicate via hash
    3. Create workflow record in DB
    4. Run through LangGraph orchestrator
    5. Return result
    """
    # Idempotency check
    payload_json = json.dumps(request.payload, sort_keys=True)
    payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()

    existing = await db.execute(
        text("SELECT id FROM workflows WHERE payload_hash = :hash"),
        {"hash": payload_hash},
    )
    if existing.first():
        raise HTTPException(
            status_code=409,
            detail=f"Duplicate workflow detected (hash: {payload_hash[:12]}...)",
        )

    # Create workflow record
    workflow_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    await db.execute(
        text(
            "INSERT INTO workflows (id, workflow_type, status, payload, "
            "payload_hash, created_by, created_at, updated_at) "
            "VALUES (:id, :type, :status, :payload, :hash, :by, :at, :at)"
        ),
        {
            "id": workflow_id,
            "type": request.workflow_type,
            "status": "pending",
            "payload": payload_json,
            "hash": payload_hash,
            "by": request.created_by,
            "at": now,
        },
    )
    await db.commit()

    # Audit
    audit = AuditLogger(db)
    await audit.log_action(
        workflow_id=workflow_id,
        agent_name="api",
        action="workflow_triggered",
        status="success",
        input_data={"workflow_type": request.workflow_type},
    )

    # Run orchestrator
    try:
        result = await run_workflow(
            workflow_type=request.workflow_type,
            payload=request.payload,
            created_by=request.created_by,
        )

        # Update DB with final status
        await db.execute(
            text(
                "UPDATE workflows SET status = :status, updated_at = :at "
                "WHERE id = :id"
            ),
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
            "details": result.get("agent_outputs", []),
        }

    except Exception as e:
        logger.error("workflow_failed", workflow_id=workflow_id, error=str(e))
        await db.execute(
            text("UPDATE workflows SET status = 'failed', updated_at = :at WHERE id = :id"),
            {"at": datetime.now(timezone.utc), "id": workflow_id},
        )
        await db.commit()
        raise HTTPException(status_code=500, detail=f"Workflow failed: {str(e)}")


@router.get("/check-hash/{payload_hash}")
async def check_hash(
    payload_hash: str,
    db: AsyncSession = Depends(get_db),
):
    """Check if a workflow with this payload hash already exists (n8n idempotency)."""
    result = await db.execute(
        text("SELECT id FROM workflows WHERE payload_hash = :hash"),
        {"hash": payload_hash},
    )
    row = result.first()
    return {"exists": row is not None, "workflow_id": str(row[0]) if row else None}


@router.get("/{workflow_id}")
async def get_workflow(
    workflow_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get workflow status and details."""
    result = await db.execute(
        text("SELECT * FROM workflows WHERE id = :id"),
        {"id": workflow_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return dict(row)


@router.get("/")
async def list_workflows(
    status: str | None = None,
    workflow_type: str | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """List workflows with optional filters."""
    query = "SELECT * FROM workflows WHERE 1=1"
    params: dict[str, Any] = {}

    if status:
        query += " AND status = :status"
        params["status"] = status
    if workflow_type:
        query += " AND workflow_type = :type"
        params["type"] = workflow_type

    query += " ORDER BY created_at DESC LIMIT :limit"
    params["limit"] = limit

    result = await db.execute(text(query), params)
    rows = result.mappings().all()
    return [dict(r) for r in rows]
