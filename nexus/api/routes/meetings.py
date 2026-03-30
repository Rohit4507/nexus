"""Meeting-specific API routes — audio upload and meeting processing."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.database import get_db
from nexus.models.schemas import WorkflowCreate
from nexus.agents.orchestrator import run_workflow
from nexus.memory.audit_logger import AuditLogger
from nexus.config import get_settings

logger = structlog.get_logger()
router = APIRouter(prefix="/meetings", tags=["meetings"])
settings = get_settings()


@router.post("/upload", response_model=dict)
async def upload_and_process_meeting(
    audio_file: Optional[UploadFile] = File(None),
    transcript: Optional[str] = Form(None),
    title: Optional[str] = Form(None),
    participants: Optional[str] = Form(None),  # JSON string
    recorded_at: Optional[str] = Form(None),  # ISO string
    auto_trigger_workflows: bool = Form(False),
    approve_high_impact_actions: bool = Form(False),
    trigger_confidence_threshold: float = Form(0.8),
    created_by: Optional[str] = Form(None),
    channel: str = Form("#meetings"),
    db: AsyncSession = Depends(get_db),
):
    """Upload audio file or provide transcript to process a meeting.
    
    Supports both audio file upload and direct transcript input.
    If both are provided, transcript takes priority (skips transcription).
    
    Args:
        audio_file: Audio file (WAV, MP3, M4A) - optional if transcript provided
        transcript: Pre-existing transcript text - optional if audio_file provided
        title: Meeting title
        participants: JSON string of participant list
        recorded_at: ISO datetime string when meeting was recorded
        auto_trigger_workflows: Whether to auto-trigger downstream workflows
        approve_high_impact_actions: Allow high-impact actions without approval
        trigger_confidence_threshold: Confidence threshold for auto-triggering
        created_by: User who triggered the workflow
        channel: Slack channel for notifications
    
    Returns:
        Workflow result with meeting processing details
    """
    if not audio_file and not transcript:
        raise HTTPException(
            status_code=400, 
            detail="Either audio_file or transcript must be provided"
        )

    # Parse participants JSON if provided
    participants_list = []
    if participants:
        try:
            import json
            participants_list = json.loads(participants)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid participants JSON")

    # Parse recorded_at if provided
    recorded_at_dt = None
    if recorded_at:
        try:
            recorded_at_dt = datetime.fromisoformat(recorded_at.replace('Z', '+00:00'))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid recorded_at datetime")

    # Handle audio file upload
    audio_file_path = None
    if audio_file:
        # Validate audio file type
        allowed_extensions = {".wav", ".mp3", ".m4a", ".flac", ".aac"}
        file_extension = "." + audio_file.filename.split(".")[-1].lower() if audio_file.filename else ""
        
        if file_extension not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type. Allowed: {', '.join(allowed_extensions)}"
            )

        # Save uploaded file to temporary location
        import os
        from pathlib import Path
        
        temp_dir = Path("data/temp_meetings")
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        filename = f"{uuid.uuid4()}{file_extension}"
        audio_file_path = temp_dir / filename
        
        with open(audio_file_path, "wb") as f:
            content = await audio_file.read()
            f.write(content)

    # Build meeting payload
    payload = {
        "title": title or "Uploaded Meeting",
        "participants": participants_list,
        "recorded_at": recorded_at_dt.isoformat() if recorded_at_dt else datetime.now(timezone.utc).isoformat(),
        "channel": channel,
        "auto_trigger_workflows": auto_trigger_workflows,
        "approve_high_impact_actions": approve_high_impact_actions,
        "trigger_confidence_threshold": trigger_confidence_threshold,
        "created_by": created_by,
    }

    # Add audio file path or transcript
    if audio_file_path:
        payload["audio_file_path"] = str(audio_file_path)
    if transcript:
        payload["transcript"] = transcript

    # Create and run workflow
    workflow_id = str(uuid.uuid4())
    try:
        result = await run_workflow(
            workflow_type="meeting",
            payload=payload,
            created_by=created_by,
            workflow_id=workflow_id,
            db_session=db,
        )

        return {
            "workflow_id": workflow_id,
            "status": result.get("status"),
            "meeting_title": title,
            "audio_uploaded": audio_file is not None,
            "transcript_provided": transcript is not None,
            "auto_trigger_workflows": auto_trigger_workflows,
            "processing_result": {
                "summary": result.get("summary"),
                "action_items_count": len(result.get("action_items", [])),
                "decisions_count": len(result.get("decisions", [])),
                "assignments_count": len(result.get("assignments", {}).get("assignments", [])),
                "downstream_workflows": result.get("downstream_workflows", []),
                "recording_storage": result.get("recording_storage"),
            },
            "phases_completed": len(result.get("agent_outputs", [])),
        }

    except Exception as e:
        logger.error("meeting_upload_failed", workflow_id=workflow_id, error=str(e))
        
        # Cleanup temp file if it exists
        if audio_file_path and os.path.exists(audio_file_path):
            os.remove(audio_file_path)
            
        raise HTTPException(status_code=500, detail=f"Meeting processing failed: {str(e)}")


@router.get("/{workflow_id}")
async def get_meeting_workflow(
    workflow_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get meeting workflow details including extracted actions."""
    from sqlalchemy import text
    
    # Get workflow details
    result = await db.execute(
        text("SELECT * FROM workflows WHERE id = :id AND workflow_type = 'meeting'"),
        {"id": workflow_id},
    )
    workflow = result.mappings().first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Meeting workflow not found")

    # Get meeting details if available
    meeting_result = await db.execute(
        text("SELECT * FROM meetings WHERE workflow_id = :id"),
        {"id": workflow_id},
    )
    meeting = meeting_result.mappings().first()

    # Get meeting actions
    actions_result = await db.execute(
        text("SELECT * FROM meeting_actions WHERE workflow_id = :id ORDER BY created_at"),
        {"id": workflow_id},
    )
    actions = actions_result.mappings().all()

    return {
        "workflow": dict(workflow),
        "meeting": dict(meeting) if meeting else None,
        "actions": [dict(action) for action in actions],
        "actions_count": len(actions),
    }
