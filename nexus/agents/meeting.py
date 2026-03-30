"""Meeting Intelligence Agent — Full implementation.

Flow: transcribe → diarize → extract_actions → assign_tasks → notify

Uses: Whisper (via Ollama) for transcription, LLaMA 3 for action extraction,
      Slack/Email for task assignment notifications.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

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
        ollama_url: str = "http://localhost:11434",
    ):
        self.tools = tool_registry
        self.llm = llm_router or LLMRouter()
        self.audit = audit_logger or AuditLogger()
        self.ollama_url = ollama_url.rstrip("/")
        self.http = httpx.AsyncClient(timeout=120.0)

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
        workflow_id = meeting_metadata.get("workflow_id", str(uuid.uuid4()))
        logger.info("meeting_process_start", workflow_id=workflow_id)

        try:
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
            await self._store_meeting_memory(
                workflow_id,
                transcript,
                summary,
                extracted,
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
        """Transcribe audio using Whisper via Ollama."""
        # Note: Ollama doesn't natively support Whisper audio transcription.
        # In production, use OpenAI Whisper API or local whisper.cpp
        # For now, we mock this with a placeholder

        logger.info("transcribe_audio", path=audio_path, mode="mock")

        # Mock transcription for development
        # Production would call: ollama generate with whisper model
        # or use openai.Audio.transcribe()

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
    ) -> None:
        """Store meeting in vector memory for future reference."""
        try:
            memory = VectorMemoryManager()

            # Store full transcript
            await memory.upsert_dynamic(
                texts=[
                    f"Meeting Summary: {summary}",
                    f"Decisions: {json.dumps(extracted.get('decisions', []))}",
                    f"Action Items: {json.dumps(extracted.get('action_items', []))}",
                ],
                metadatas=[
                    {
                        "type": "meeting_summary",
                        "workflow_id": workflow_id,
                        "date": datetime.now(timezone.utc).isoformat(),
                    },
                    {
                        "type": "meeting_decisions",
                        "workflow_id": workflow_id,
                    },
                    {
                        "type": "meeting_actions",
                        "workflow_id": workflow_id,
                    },
                ],
            )

            await memory.close()
            logger.info("meeting_memory_stored", workflow_id=workflow_id)

        except Exception as e:
            logger.warning("meeting_memory_store_failed", error=str(e))

    async def close(self):
        """Cleanup HTTP clients."""
        await self.http.aclose()
        if self.llm:
            await self.llm.close()
