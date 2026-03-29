"""Pydantic schemas for API request/response validation."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Workflow Schemas ─────────────────────────────────────────────────────────

class WorkflowCreate(BaseModel):
    workflow_type: str = Field(..., pattern="^(procurement|onboarding|contract|meeting)$")
    payload: dict[str, Any]
    created_by: Optional[str] = None

class WorkflowResponse(BaseModel):
    id: uuid.UUID
    workflow_type: str
    status: str
    payload: dict[str, Any]
    payload_hash: Optional[str] = None
    sla_deadline: Optional[datetime] = None
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

class WorkflowUpdate(BaseModel):
    status: Optional[str] = None
    payload: Optional[dict[str, Any]] = None


# ── Approval Schemas ─────────────────────────────────────────────────────────

class ApprovalCreate(BaseModel):
    workflow_id: uuid.UUID
    approver: str

class ApprovalDecision(BaseModel):
    status: str = Field(..., pattern="^(approved|rejected)$")
    comments: Optional[str] = None

class ApprovalResponse(BaseModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    approver: str
    status: str
    comments: Optional[str] = None
    requested_at: datetime
    decided_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ── Audit Log Schemas ────────────────────────────────────────────────────────

class AuditLogResponse(BaseModel):
    id: int
    workflow_id: Optional[uuid.UUID] = None
    agent_name: str
    action: str
    status: str
    error_message: Optional[str] = None
    duration_ms: Optional[int] = None
    llm_tier: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Meeting Schemas ──────────────────────────────────────────────────────────

class MeetingCreate(BaseModel):
    title: Optional[str] = None
    participants: Optional[dict] = None
    recorded_at: Optional[datetime] = None

class MeetingResponse(BaseModel):
    id: uuid.UUID
    title: Optional[str] = None
    summary: Optional[str] = None
    participants: Optional[dict] = None
    recorded_at: Optional[datetime] = None
    processed_at: datetime

    model_config = {"from_attributes": True}

class MeetingActionResponse(BaseModel):
    id: uuid.UUID
    meeting_id: uuid.UUID
    action_text: str
    assignee: Optional[str] = None
    due_date: Optional[date] = None
    priority: str
    status: str
    workflow_id: Optional[uuid.UUID] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Failed Trigger Schemas ───────────────────────────────────────────────────

class FailedTriggerResponse(BaseModel):
    id: int
    source: str
    payload: dict[str, Any]
    error: str
    retries: int
    can_replay: bool
    created_at: datetime
    replayed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ── Health Check ─────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    database: str
    redis: str
