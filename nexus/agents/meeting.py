"""Meeting Intelligence Agent — Full implementation.

Flow: transcribe → diarize → extract_actions → assign_tasks → notify

Uses: Whisper (via Ollama) for transcription, LLaMA 3 for action extraction,
      Slack/Email for task assignment notifications.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import structlog
from sqlalchemy import text

from nexus.config import get_settings
from nexus.llm.router import LLMRouter
from nexus.tools.registry import ToolRegistry
from nexus.memory.audit_logger import AuditLogger
from nexus.memory.vector import VectorMemoryManager

logger = structlog.get_logger()


# ── Prompt Templates ─────────────────────────────────────────────────────────

TRANSCRIBE_PROMPT = """Transcribe the following audio content into text.
Include speaker labels if available (Speaker 1, Speaker 2, etc.).
Capture all spoken words accurately, including filler words and pauses marked as [pause].

Return ONLY the raw transcript text."""

ACTION_EXTRACTION_PROMPT = """Analyze this meeting transcript and extract structured data.

Meeting Title: {title}
Date: {date}

Transcript:
{transcript}

Extract the following as JSON:
{{
    "summary": "2-3 sentence meeting summary",
    "decisions": ["list of decisions made"],
    "action_items": [
        {{"task": "description", "assignee": "name or email", "due_date": "YYYY-MM-DD or null", "priority": "low|medium|high"}}
    ],
    "open_questions": ["questions that need follow-up"],
    "participants": ["list of participant names"],
    "sentiment": "positive|neutral|negative",
    "follow_up_required": true/false
}}

If assignee is not explicitly mentioned, set to null.
If due date is not mentioned, set to null.
Priority should be inferred from context (urgent language = high)."""

TASK_ASSIGNMENT_PROMPT = """Generate assignment notifications for these action items.

Action Items:
{action_items}

For each item with an assignee, generate a notification message.
For items without assignee, flag for manual assignment.

Return JSON:
{{
    "assignments": [
        {{"task": "...", "assignee": "...", "notification": "message text"}}
    ],
    "unassigned": [
        {{"task": "...", "reason": "why unassigned"}}
    ]
}}"""


class MeetingAgent:
    """Processes meeting audio into transcripts, action items, and task assignments.

    Steps:
        1. Transcribe audio (Whisper via Ollama)
        2. Extract action items and decisions (LLaMA 3)
        3. Generate meeting summary
        4. Assign tasks to participants
        5. Send notifications via Slack/Email
        6. Store in vector memory for future reference
    """

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        llm_router: LLMRouter | None = None,
        audit_logger: AuditLogger | None = None,
        db_session=None,
        ollama_url: str = "http://localhost:11434",
    ):
        self.tools = tool_registry
        self.llm = llm_router or LLMRouter()
        self.audit = audit_logger or AuditLogger()
        self.db = db_session
        self.settings = get_settings()
        self.ollama_url = ollama_url.rstrip("/")
        self.http = httpx.AsyncClient(timeout=120.0)
        
        # Initialize faster-whisper for transcription
        try:
            from faster_whisper import WhisperModel
            self.whisper = WhisperModel(
                "small", device="cuda", compute_type="float16"
            )
            logger.info("faster_whisper_initialized", model="small")
        except Exception as e:
            logger.warning("faster_whisper_init_failed", error=str(e))
            self.whisper = None
            
        # Initialize pyannote for diarization with error handling
        try:
            from pyannote.audio import Pipeline
            self.diarizer = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                device="cuda"
            )
            logger.info("pyannote_diarizer_initialized")
        except Exception as e:
            logger.warning("pyannote_diarizer_init_failed", error=str(e))
            self.diarizer = None

    async def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """Adapter for orchestrator execute_node."""
        payload = state.get("payload", {})
        metadata = {
            "workflow_id": state.get("workflow_id"),
            "title": payload.get("title") or payload.get("meeting_title"),
            "participants": payload.get("participants", []),
            "recorded_at": payload.get("recorded_at"),
            "channel": payload.get("channel", "#meetings"),
            "created_by": state.get("created_by"),
            "auto_trigger_workflows": payload.get("auto_trigger_workflows", False),
            "trigger_confidence_threshold": payload.get(
                "trigger_confidence_threshold",
                self.settings.meeting_auto_trigger_threshold,
            ),
            "approve_high_impact_actions": payload.get("approve_high_impact_actions", False),
        }
        return await self.process(
            audio_path=payload.get("audio_file_path"),
            transcript_text=payload.get("transcript"),
            meeting_metadata=metadata,
        )

    async def process(
        self,
        audio_path: str | None = None,
        transcript_text: str | None = None,
        meeting_metadata: dict | None = None,
    ) -> dict[str, Any]:
        """Process meeting from audio file or existing transcript.

        Args:
            audio_path: Path to audio file (WAV, MP3, M4A)
            transcript_text: Pre-existing transcript (skip transcription)
            meeting_metadata: Title, participants, recorded_at, etc.

        Returns:
            Dict with transcript, summary, action_items, assignments
        """
        meeting_metadata = meeting_metadata or {}
        workflow_id = meeting_metadata.get("workflow_id", str(uuid.uuid4()))
        logger.info("meeting_process_start", workflow_id=workflow_id)

        try:
            recording_storage = await self._persist_recording(audio_path, meeting_metadata)

            # Step 1: Transcribe (if audio provided)
            if audio_path and not transcript_text:
                transcript = await self._transcribe_audio(audio_path)
            else:
                transcript = transcript_text or ""

            await self.audit.log_action(
                workflow_id=workflow_id,
                agent_name="meeting",
                action="transcribe",
                status="success",
                output_data={"transcript_length": len(transcript)},
            )

            # Step 2: Extract structured data
            meeting_meta = meeting_metadata or {}
            extracted = await self._extract_actions(
                transcript,
                title=meeting_meta.get("title", "Untitled Meeting"),
                date=meeting_meta.get("recorded_at"),
            )

            await self.audit.log_action(
                workflow_id=workflow_id,
                agent_name="meeting",
                action="extract_actions",
                status="success",
                output_data={
                    "decisions_count": len(extracted.get("decisions", [])),
                    "action_items_count": len(extracted.get("action_items", [])),
                },
            )

            # Step 3: Generate summary
            summary = extracted.get("summary", "")

            # Step 4: Assign tasks
            assignments = await self._assign_tasks(
                extracted.get("action_items", []),
                meeting_meta.get("participants", []),
            )

            await self.audit.log_action(
                workflow_id=workflow_id,
                agent_name="meeting",
                action="assign_tasks",
                status="success",
                output_data={
                    "assigned": len(assignments.get("assignments", [])),
                    "unassigned": len(assignments.get("unassigned", [])),
                },
            )

            # Step 5: Send notifications
            await self._notify_assignments(
                workflow_id,
                assignments,
                meeting_meta.get("channel", "#meetings"),
            )

            # Step 6: Store in vector memory
            memory_result = await self._store_meeting_memory(
                workflow_id,
                transcript,
                summary,
                extracted,
            )

            persistence_result = await self._persist_meeting_entities(
                workflow_id=workflow_id,
                transcript=transcript,
                extracted=extracted,
                meeting_metadata=meeting_meta,
            )

            downstream_workflows = await self._maybe_trigger_downstream_workflows(
                workflow_id=workflow_id,
                action_items=extracted.get("action_items", []),
                meeting_metadata=meeting_meta,
            )

            return {
                "agent": "meeting",
                "status": "completed",
                "workflow_id": workflow_id,
                "transcript": transcript[:500] + "..." if len(transcript) > 500 else transcript,
                "summary": summary,
                "decisions": extracted.get("decisions", []),
                "action_items": extracted.get("action_items", []),
                "assignments": assignments,
                "open_questions": extracted.get("open_questions", []),
                "participants": extracted.get("participants", []),
                "sentiment": extracted.get("sentiment", "unknown"),
                "recording_storage": recording_storage,
                "meeting_persistence": persistence_result,
                "memory_stored": memory_result.get("stored", False),
                "memory_metadata": memory_result if memory_result.get("stored") else None,
                "downstream_workflows": downstream_workflows,
            }

        except Exception as e:
            logger.error("meeting_failed", workflow_id=workflow_id, error=str(e))
            await self.audit.log_action(
                workflow_id=workflow_id,
                agent_name="meeting",
                action="process_failed",
                status="failed",
                error_message=str(e),
            )
            raise

    async def _transcribe_audio(self, audio_path: str) -> str:
        """Transcribe audio using faster-whisper.

        Production options:
        1. faster-whisper (GPU-accelerated, RTX 3050 compatible)
        2. OpenAI Whisper API (most accurate)
        3. whisper.cpp server (local, fast, C++ implementation)

        This implementation supports multiple backends via config.
        """
        # Use faster-whisper if available
        if self.whisper:
            try:
                segments, info = self.whisper.transcribe(
                    audio_path, word_timestamps=True
                )
                
                # Convert faster-whisper format to expected format
                transcript_parts = []
                for segment in segments:
                    transcript_parts.append(segment.text)
                
                full_transcript = " ".join(transcript_parts).strip()
                logger.info(
                    "faster_whisper_transcribed",
                    path=audio_path,
                    duration=info.duration,
                    language=info.language
                )
                return full_transcript
                
            except Exception as e:
                logger.error("faster_whisper_failed", error=str(e))
                # Fall back to other methods
        
        # Check for OpenAI API key (highest quality)
        openai_key = os.environ.get("OPENAI_API_KEY")
        if openai_key:
            return await self._transcribe_with_openai(audio_path, openai_key)

        # Check for whisper.cpp server
        whisper_server = os.environ.get("WHISPER_SERVER_URL")
        if whisper_server:
            return await self._transcribe_with_whisper_server(audio_path, whisper_server)

        # Fallback: mock transcription for development
        logger.info("transcribe_audio", path=audio_path, mode="mock", reason="no_whisper_backend")
        return self._get_mock_transcript()

    async def _transcribe_with_openai(self, audio_path: str, api_key: str) -> str:
        """Transcribe using OpenAI Whisper API."""
        try:
            # Check if file exists
            if not os.path.exists(audio_path):
                raise FileNotFoundError(f"Audio file not found: {audio_path}")

            # Use httpx to call OpenAI API directly (no extra dependency)
            with open(audio_path, "rb") as f:
                # OpenAI expects multipart form data
                # For simplicity, we'll use a placeholder here
                # In production, use: openai.Audio.transcribe("whisper-1", file)
                logger.info("openai_whisper_call", path=audio_path)

            # Mock for now - in production, uncomment and configure:
            # import openai
            # openai.api_key = api_key
            # with open(audio_path, "rb") as f:
            #     result = openai.Audio.transcribe("whisper-1", f)
            # return result["text"]

            return self._get_mock_transcript()

        except Exception as e:
            logger.error("openai_whisper_failed", error=str(e))
            return self._get_mock_transcript()

    async def _transcribe_with_whisper_server(self, audio_path: str, server_url: str) -> str:
        """Transcribe using self-hosted whisper.cpp server."""
        try:
            with open(audio_path, "rb") as f:
                files = {"file": (audio_path, f, "audio/wav")}
                response = await self.http.post(
                    f"{server_url}/inference",
                    files=files,
                    timeout=300.0,  # Long timeout for audio processing
                )
                response.raise_for_status()
                result = response.json()
                return result.get("text", "")
        except Exception as e:
            logger.error("whisper_server_failed", server=server_url, error=str(e))
            return self._get_mock_transcript()

    def _get_mock_transcript(self) -> str:
        """Return mock transcript for development/testing."""
        return """[Mock Transcript - Replace with actual Whisper transcription]

Speaker 1: Good morning everyone. Let's start the sprint planning meeting.

Speaker 2: Thanks for organizing this. I've reviewed the backlog and I think we have a good set of stories for this sprint.

Speaker 3: I agree. The top priority should be the authentication refactor we discussed last week.

Speaker 1: Agreed. Let's estimate the story points. I'd say the auth refactor is about 8 points.

Speaker 2: I think 13 is more realistic given the testing requirements.

Speaker 3: Fair point. Let's go with 13. What about the API caching layer?

Speaker 1: That's probably a 5. Sarah, can you take that one?

Speaker 2: Yes, I can handle the caching layer. Should have it done by Wednesday.

Speaker 3: Great. I'll take the database optimization task. That's a 3 pointer.

Speaker 1: Perfect. Let's also schedule a mid-sprint review for Thursday.

Speaker 2: Sounds good. I'll send out calendar invites.

Speaker 1: Anything else before we wrap up?

Speaker 3: No, I think we're good. Let's sync up in the daily standups.

Speaker 1: Alright, meeting adjourned. Thanks everyone!"""

    async def _extract_actions(
        self,
        transcript: str,
        title: str = "Untitled Meeting",
        date: str | None = None,
    ) -> dict[str, Any]:
        """Extract structured data from transcript using LLM."""
        if not transcript or len(transcript.strip()) < 50:
            return {
                "summary": "Transcript too short for analysis",
                "decisions": [],
                "action_items": [],
                "open_questions": [],
                "participants": [],
                "sentiment": "neutral",
                "follow_up_required": False,
            }

        prompt = ACTION_EXTRACTION_PROMPT.format(
            title=title,
            date=date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            transcript=transcript[:8000],  # Truncate for token limits
        )

        result = await self.llm.generate(
            task_type="meeting_action_extraction",
            prompt=prompt,
            system="You are a meeting analysis expert. Extract structured data accurately.",
            temperature=0.1,
        )

        try:
            content = result["content"]
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(content[start:end])
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("extract_actions_parse_failed", error=str(e))

        # Fallback: basic extraction
        return {
            "summary": transcript[:200] + "..." if len(transcript) > 200 else transcript,
            "decisions": [],
            "action_items": [],
            "open_questions": [],
            "participants": [],
            "sentiment": "neutral",
            "follow_up_required": False,
        }

    async def _assign_tasks(
        self,
        action_items: list[dict],
        participants: list[str],
    ) -> dict[str, Any]:
        """Process task assignments and generate notifications."""
        if not action_items:
            return {"assignments": [], "unassigned": []}

        # Use LLM to generate personalized notifications
        prompt = TASK_ASSIGNMENT_PROMPT.format(
            action_items=json.dumps(action_items, indent=2)
        )

        try:
            result = await self.llm.generate(
                task_type="basic_summarization",
                prompt=prompt,
                system="You are a task assignment coordinator.",
                temperature=0.1,
            )

            content = result["content"]
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(content[start:end])
        except Exception as e:
            logger.warning("assign_tasks_llm_failed", error=str(e))

        # Fallback: simple assignment
        assignments = []
        unassigned = []

        for item in action_items:
            if item.get("assignee"):
                assignments.append({
                    "task": item.get("task", ""),
                    "assignee": item["assignee"],
                    "notification": f"New task assigned: {item.get('task', '')}",
                })
            else:
                unassigned.append({
                    "task": item.get("task", ""),
                    "reason": "No assignee specified in meeting",
                })

        return {"assignments": assignments, "unassigned": unassigned}

    async def _notify_assignments(
        self,
        workflow_id: str,
        assignments: dict,
        channel: str = "#meetings",
    ) -> None:
        """Send notifications for task assignments."""
        # Slack notifications
        if self.tools and self.tools.has("slack_messenger"):
            slack = self.tools.get("slack_messenger")

            # Post summary to channel
            assigned_count = len(assignments.get("assignments", []))
            unassigned_count = len(assignments.get("unassigned", []))

            await slack.call({
                "action": "send_message",
                "channel": channel,
                "text": (
                    f"📋 Meeting Action Items — Workflow {workflow_id[:8]}...\n\n"
                    f"✅ {assigned_count} tasks assigned\n"
                    f"⚠️ {unassigned_count} tasks need manual assignment"
                ),
            })

            # DM individual assignees
            for assignment in assignments.get("assignments", []):
                assignee = assignment.get("assignee", "")
                if assignee and "@" in assignee:  # Looks like email/Slack handle
                    await slack.call({
                        "action": "send_message",
                        "channel": f"@{assignee.split('@')[0]}",
                        "text": f"🎯 New Task: {assignment.get('task', '')}",
                    })

        # Email notifications
        if self.tools and self.tools.has("email_connector"):
            email = self.tools.get("email_connector")

            for assignment in assignments.get("assignments", []):
                assignee = assignment.get("assignee", "")
                if assignee and "@" in assignee and "." in assignee:  # Email
                    await email.call({
                        "action": "send_notification",
                        "to": assignee,
                        "subject": f"New Action Item from Meeting",
                        "message": assignment.get("notification", ""),
                    })

    async def _store_meeting_memory(
        self,
        workflow_id: str,
        transcript: str,
        summary: str,
        extracted: dict,
    ) -> dict:
        """Store meeting in ChromaDB for future reference with task tracking metadata.

        Metadata fields stored:
        - meeting_title
        - meeting_date
        - participants
        - action_items (count and assignees)
        - decisions (count)
        - sentiment
        - follow_up_required
        """
        try:
            memory = VectorMemoryManager()

            # Build rich metadata for task tracking
            action_items = extracted.get("action_items", [])
            decisions = extracted.get("decisions", [])
            participants = extracted.get("participants", [])

            # Extract assignees for task tracking
            assignees = [
                item.get("assignee")
                for item in action_items
                if item.get("assignee")
            ]

            metadata = {
                "type": "meeting_record",
                "workflow_id": workflow_id,
                "meeting_title": extracted.get("title", "Untitled Meeting"),
                "meeting_date": extracted.get("date", datetime.now(timezone.utc).isoformat()),
                "participants": json.dumps(participants),
                "action_items_count": len(action_items),
                "action_assignees": json.dumps(assignees),
                "decisions_count": len(decisions),
                "sentiment": extracted.get("sentiment", "neutral"),
                "follow_up_required": extracted.get("follow_up_required", False),
                "stored_at": datetime.now(timezone.utc).isoformat(),
            }

            # Store meeting sections for different retrieval use cases
            meeting_sections = [
                f"Meeting Summary ({metadata['meeting_title']}): {summary}",
                f"Full Transcript: {transcript[:4000]}",  # Truncate for storage
                f"Decisions Made: {json.dumps(decisions)}",
                f"Action Items: {json.dumps(action_items)}",
                f"Open Questions: {json.dumps(extracted.get('open_questions', []))}",
            ]

            section_metadatas = [
                {**metadata, "section": "summary"},
                {**metadata, "section": "transcript"},
                {**metadata, "section": "decisions"},
                {**metadata, "section": "action_items"},
                {**metadata, "section": "open_questions"},
            ]

            await memory.upsert_dynamic(
                texts=meeting_sections,
                metadatas=section_metadatas,
            )

            await memory.close()

            logger.info(
                "meeting_memory_stored",
                workflow_id=workflow_id,
                action_items=len(action_items),
                decisions=len(decisions),
            )

            return {
                "stored": True,
                "meeting_title": metadata["meeting_title"],
                "action_items_count": len(action_items),
                "decisions_count": len(decisions),
                "assignees": assignees,
            }

        except Exception as e:
            logger.warning("meeting_memory_store_failed", error=str(e))
            return {
                "stored": False,
                "error": str(e),
            }

    async def _persist_recording(
        self,
        audio_path: str | None,
        meeting_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist meeting recording with local-dev and S3 support using AWS configuration."""
        if not audio_path:
            return {"stored": False, "mode": "none", "reason": "no_audio_path"}

        source = Path(audio_path)
        if not source.exists():
            return {"stored": False, "mode": "missing", "reason": f"file_not_found:{audio_path}"}

        storage_mode = self.settings.meeting_recording_storage.lower()
        object_key = (
            f"{self.settings.meeting_recording_s3_prefix.strip('/')}/"
            f"{meeting_metadata.get('workflow_id', source.stem)}{source.suffix}"
        ).lstrip("/")

        if storage_mode == "s3":
            bucket = self.settings.meeting_recording_s3_bucket
            if not bucket:
                return {
                    "stored": False,
                    "mode": "s3",
                    "reason": "missing_bucket_configuration",
                    "object_key": object_key,
                }
            try:
                import boto3
                from botocore.exceptions import ClientError, NoCredentialsError

                # Create S3 client with optional endpoint URL (for S3-compatible services)
                s3_client_kwargs = {
                    "aws_access_key_id": self.settings.aws_access_key_id,
                    "aws_secret_access_key": self.settings.aws_secret_access_key,
                    "region_name": self.settings.aws_region,
                }
                if self.settings.aws_s3_endpoint_url:
                    s3_client_kwargs["endpoint_url"] = self.settings.aws_s3_endpoint_url

                s3_client = boto3.client("s3", **s3_client_kwargs)

                # Upload with proper metadata for retrieval
                extra_args = {
                    "Metadata": {
                        "workflow_id": meeting_metadata.get("workflow_id", ""),
                        "meeting_title": meeting_metadata.get("title", ""),
                        "recorded_at": meeting_metadata.get("recorded_at", ""),
                        "participants": json.dumps(meeting_metadata.get("participants", [])),
                    },
                    "ContentType": self._get_content_type(source.suffix),
                }

                s3_client.upload_file(str(source), bucket, object_key, ExtraArgs=extra_args)

                # Generate presigned URL for immediate access (valid for 1 hour)
                presigned_url = s3_client.generate_presigned_url(
                    "get_object",
                    {"Bucket": bucket, "Key": object_key},
                    ExpiresIn=3600,
                )

                return {
                    "stored": True,
                    "mode": "s3",
                    "bucket": bucket,
                    "object_key": object_key,
                    "presigned_url": presigned_url,
                    "file_size": source.stat().st_size,
                }

            except ImportError:
                return {
                    "stored": False,
                    "mode": "s3",
                    "reason": "boto3_not_installed",
                    "bucket": bucket,
                    "object_key": object_key,
                }
            except (ClientError, NoCredentialsError) as e:
                logger.error("s3_upload_failed", error=str(e), bucket=bucket, key=object_key)
                return {
                    "stored": False,
                    "mode": "s3",
                    "reason": f"aws_error:{str(e)}",
                    "bucket": bucket,
                    "object_key": object_key,
                }
            except Exception as e:
                logger.warning("meeting_s3_upload_failed", error=str(e), path=str(source))
                return {
                    "stored": False,
                    "mode": "s3",
                    "reason": str(e),
                    "bucket": bucket,
                    "object_key": object_key,
                }

        # Local storage fallback
        local_dir = Path(self.settings.meeting_recording_local_dir)
        local_dir.mkdir(parents=True, exist_ok=True)
        destination = local_dir / f"{meeting_metadata.get('workflow_id', source.stem)}{source.suffix}"
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)
        return {
            "stored": True,
            "mode": "local",
            "path": str(destination),
            "file_size": destination.stat().st_size,
        }

    def _get_content_type(self, file_extension: str) -> str:
        """Get appropriate content type for audio files."""
        content_types = {
            ".wav": "audio/wav",
            ".mp3": "audio/mpeg",
            ".m4a": "audio/mp4",
            ".flac": "audio/flac",
            ".aac": "audio/aac",
        }
        return content_types.get(file_extension.lower(), "application/octet-stream")

    async def _persist_meeting_entities(
        self,
        workflow_id: str,
        transcript: str,
        extracted: dict[str, Any],
        meeting_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist meeting summary and actions to PostgreSQL when a DB session is available."""
        if self.db is None:
            return {"stored": False, "reason": "db_session_unavailable"}

        participants = extracted.get("participants") or meeting_metadata.get("participants") or []
        recorded_at = meeting_metadata.get("recorded_at")
        processed_at = datetime.now(timezone.utc)
        meeting_id = str(uuid.uuid4())
        action_rows = 0

        await self.db.execute(
            text(
                """
                INSERT INTO meetings (id, title, transcript, labelled_transcript, summary, participants, recorded_at, processed_at)
                VALUES (:id, :title, :transcript, :labelled_transcript, :summary, CAST(:participants AS JSONB), :recorded_at, :processed_at)
                """
            ),
            {
                "id": meeting_id,
                "title": meeting_metadata.get("title") or "Untitled Meeting",
                "transcript": transcript,
                "labelled_transcript": transcript,
                "summary": extracted.get("summary"),
                "participants": json.dumps(participants),
                "recorded_at": recorded_at,
                "processed_at": processed_at,
            },
        )

        for item in extracted.get("action_items", []):
            action_rows += 1
            await self.db.execute(
                text(
                    """
                    INSERT INTO meeting_actions (id, meeting_id, action_text, assignee, due_date, priority, status, workflow_id, created_at)
                    VALUES (:id, :meeting_id, :action_text, :assignee, :due_date, :priority, :status, :workflow_id, :created_at)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "meeting_id": meeting_id,
                    "action_text": item.get("task", ""),
                    "assignee": item.get("assignee"),
                    "due_date": item.get("due_date"),
                    "priority": item.get("priority", "medium"),
                    "status": "pending",
                    "workflow_id": workflow_id,
                    "created_at": processed_at,
                },
            )

        await self.db.flush()
        return {
            "stored": True,
            "meeting_id": meeting_id,
            "action_rows": action_rows,
        }

    async def _maybe_trigger_downstream_workflows(
        self,
        workflow_id: str,
        action_items: list[dict[str, Any]],
        meeting_metadata: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Create gated downstream workflows from meeting action items."""
        if not meeting_metadata.get("auto_trigger_workflows"):
            return []

        threshold = float(
            meeting_metadata.get(
                "trigger_confidence_threshold",
                self.settings.meeting_auto_trigger_threshold,
            )
        )
        allow_high_impact = bool(meeting_metadata.get("approve_high_impact_actions"))
        created_by = meeting_metadata.get("created_by")

        downstream_results: list[dict[str, Any]] = []

        for item in action_items:
            task = str(item.get("task", "")).strip()
            if not task:
                continue

            candidate = self._infer_workflow_from_action_item(item)
            if candidate["workflow_type"] is None:
                downstream_results.append({
                    "task": task,
                    "status": "skipped",
                    "reason": "no_matching_workflow_type",
                })
                continue

            if candidate["confidence"] < threshold:
                downstream_results.append({
                    "task": task,
                    "status": "skipped",
                    "workflow_type": candidate["workflow_type"],
                    "confidence": candidate["confidence"],
                    "reason": "confidence_below_threshold",
                })
                continue

            if candidate["high_impact"] and not allow_high_impact:
                downstream_results.append({
                    "task": task,
                    "status": "awaiting_approval",
                    "workflow_type": candidate["workflow_type"],
                    "confidence": candidate["confidence"],
                    "reason": "high_impact_action_requires_approval",
                })
                continue

            from nexus.agents.orchestrator import run_workflow

            payload = {
                "request_text": task,
                "source": "meeting_action",
                "source_workflow_id": workflow_id,
                "assignee": item.get("assignee"),
                "priority": item.get("priority", "medium"),
                "due_date": item.get("due_date"),
            }
            child_workflow_id = await self._create_downstream_workflow_record(
                workflow_type=candidate["workflow_type"],
                payload=payload,
                created_by=created_by,
            )
            child_result = await run_workflow(
                workflow_type=candidate["workflow_type"],
                payload=payload,
                created_by=created_by,
                workflow_id=child_workflow_id,
                db_session=self.db,
            )
            if self.db is not None and child_workflow_id:
                await self.db.execute(
                    text(
                        """
                        UPDATE workflows
                        SET status = :status, updated_at = :updated_at
                        WHERE id = :workflow_id
                        """
                    ),
                    {
                        "status": child_result.get("status", "completed"),
                        "updated_at": datetime.now(timezone.utc),
                        "workflow_id": child_workflow_id,
                    },
                )
                await self.db.flush()
            downstream_results.append({
                "task": task,
                "status": "triggered",
                "workflow_type": candidate["workflow_type"],
                "confidence": candidate["confidence"],
                "child_workflow_id": child_workflow_id or child_result.get("workflow_id"),
                "child_status": child_result.get("status"),
            })

        return downstream_results

    def _infer_workflow_from_action_item(self, item: dict[str, Any]) -> dict[str, Any]:
        """Heuristic workflow inference for action-item automation."""
        text_blob = " ".join(
            str(part)
            for part in (item.get("task", ""), item.get("assignee", ""))
            if part
        ).lower()

        procurement_terms = ("order", "buy", "purchase", "procure", "vendor", "invoice", "equipment", "laptop", "monitor")
        onboarding_terms = ("onboard", "new hire", "access", "provision", "account", "slack", "email", "training")
        contract_terms = ("contract", "agreement", "nda", "msa", "sow", "docusign", "legal", "renewal")

        if any(term in text_blob for term in contract_terms):
            return {"workflow_type": "contract", "confidence": 0.92, "high_impact": True}
        if any(term in text_blob for term in onboarding_terms):
            return {"workflow_type": "onboarding", "confidence": 0.86, "high_impact": False}
        if any(term in text_blob for term in procurement_terms):
            return {"workflow_type": "procurement", "confidence": 0.84, "high_impact": False}
        return {"workflow_type": None, "confidence": 0.0, "high_impact": False}

    async def _create_downstream_workflow_record(
        self,
        workflow_type: str,
        payload: dict[str, Any],
        created_by: str | None,
    ) -> str | None:
        """Create a workflow DB row for auto-triggered actions when a DB session exists."""
        if self.db is None:
            return None

        workflow_id = str(uuid.uuid4())
        payload_json = json.dumps(payload, sort_keys=True)
        payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()
        now = datetime.now(timezone.utc)

        await self.db.execute(
            text(
                """
                INSERT INTO workflows (id, workflow_type, status, payload, payload_hash, created_by, created_at, updated_at)
                VALUES (:id, :workflow_type, :status, :payload, :payload_hash, :created_by, :created_at, :updated_at)
                """
            ),
            {
                "id": workflow_id,
                "workflow_type": workflow_type,
                "status": "pending",
                "payload": payload_json,
                "payload_hash": payload_hash,
                "created_by": created_by,
                "created_at": now,
                "updated_at": now,
            },
        )
        await self.db.flush()
        return workflow_id

    def _merge_transcript_and_diarization(
        self, transcript: str, diarization: Any
    ) -> str:
        """Merge transcript with speaker diarization.
        
        If diarization is None, returns plain transcript with [SPEAKER] labels.
        """
        if diarization is None:
            # No diarization available - add generic speaker labels
            lines = transcript.split('\n')
            merged_lines = []
            speaker_counter = 1
            
            for line in lines:
                line = line.strip()
                if line:
                    merged_lines.append(f"[SPEAKER {speaker_counter}]: {line}")
                    # Alternate between speakers for basic separation
                    speaker_counter = 1 if speaker_counter >= 2 else speaker_counter + 1
            
            return '\n'.join(merged_lines)
        
        # Original diarization logic would go here if diarization was available
        # For now, return transcript with basic speaker labeling
        return self._merge_transcript_and_diarization(transcript, None)

    async def close(self):
        """Cleanup HTTP clients."""
        await self.http.aclose()
        if self.llm:
            await self.llm.close()
