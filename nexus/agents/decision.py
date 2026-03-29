"""Decision Agent — intent classification, slot extraction, approval routing.

Uses LLMRouter Tier 1 for fast classification and Tier 2 for risk scoring.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import structlog

from nexus.llm.router import LLMRouter

logger = structlog.get_logger()


# ── Prompt Templates ─────────────────────────────────────────────────────────

CLASSIFY_PROMPT = """Classify the following enterprise request into exactly one category.

Categories:
- procurement: Purchase requests, vendor orders, PO creation, payment processing
- onboarding: New hire setup, IT provisioning, training assignment, HR records
- contract: Contract drafting, review, renewal, signature, compliance
- meeting: Meeting transcription, action item extraction, follow-up tracking

Request: {request_text}

Respond with ONLY a JSON object:
{{"category": "<category>", "confidence": <0.0-1.0>, "reasoning": "<brief>"}}"""

SLOT_EXTRACTION_PROMPT = """Extract structured data from this {workflow_type} request.

Request: {request_text}

Extract all relevant fields as a JSON object. Include:
- For procurement: item, quantity, unit_price, total_budget, department, urgency, vendor
- For onboarding: employee_name, role, department, start_date, equipment_needed, access_level
- For contract: contract_type, counterparty, value, start_date, end_date, key_terms
- For meeting: title, date, participants, agenda_items

Only include fields that are explicitly mentioned or can be inferred.
Respond with ONLY a valid JSON object."""

APPROVAL_ROUTING_PROMPT = """Determine the approval routing for this request.

Workflow type: {workflow_type}
Extracted data: {extracted_data}

Rules:
- Procurement < $5,000: auto-approve
- Procurement $5,000–$50,000: manager approval
- Procurement > $50,000: VP approval
- Onboarding: auto-approve (HR pre-validated)
- Contract < $10,000: manager approval
- Contract >= $10,000: legal + VP approval

Respond with ONLY a JSON object:
{{"approval_required": true/false, "approver_role": "<role>", "reason": "<brief>"}}"""


class DecisionAgent:
    """Classifies requests, extracts slots, and determines approval routing.

    Uses LLMRouter for tiered LLM access:
    - Tier 1: Classification + slot extraction (fast)
    - Tier 2: Risk scoring + complex approval logic
    """

    def __init__(self, llm_router: LLMRouter):
        self.llm = llm_router

    async def classify(self, request_text: str) -> dict[str, Any]:
        """Classify a request into a workflow type.

        Returns:
            {"category": str, "confidence": float, "reasoning": str}
        """
        logger.info("decision_classify_start", text_len=len(request_text))

        result = await self.llm.generate(
            task_type="intent_classification",
            prompt=CLASSIFY_PROMPT.format(request_text=request_text),
            system="You are a precise enterprise request classifier.",
            temperature=0.05,
        )

        try:
            parsed = json.loads(result["content"])
        except json.JSONDecodeError:
            # Try to extract JSON from response
            content = result["content"]
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                parsed = json.loads(content[start:end])
            else:
                parsed = {
                    "category": "procurement",
                    "confidence": 0.3,
                    "reasoning": "Failed to parse LLM response, defaulting",
                }

        logger.info(
            "decision_classified",
            category=parsed.get("category"),
            confidence=parsed.get("confidence"),
            tier=result["tier"],
            latency_ms=result["latency_ms"],
        )

        return {
            **parsed,
            "llm_tier": result["tier"],
            "latency_ms": result["latency_ms"],
        }

    async def extract_slots(
        self, request_text: str, workflow_type: str
    ) -> dict[str, Any]:
        """Extract structured data from the request.

        Returns:
            Dict of extracted fields relevant to the workflow type.
        """
        logger.info("decision_extract_start", workflow_type=workflow_type)

        result = await self.llm.generate(
            task_type="slot_filling",
            prompt=SLOT_EXTRACTION_PROMPT.format(
                workflow_type=workflow_type,
                request_text=request_text,
            ),
            system="You are a precise data extraction assistant.",
            temperature=0.05,
        )

        try:
            parsed = json.loads(result["content"])
        except json.JSONDecodeError:
            content = result["content"]
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                parsed = json.loads(content[start:end])
            else:
                parsed = {"raw_text": request_text, "extraction_failed": True}

        logger.info(
            "decision_extracted",
            fields=list(parsed.keys()),
            tier=result["tier"],
        )

        return parsed

    async def determine_approval(
        self, workflow_type: str, extracted_data: dict
    ) -> dict[str, Any]:
        """Determine if approval is needed and who should approve.

        Uses Tier 2 for complex reasoning about approval chains.
        """
        logger.info("decision_approval_start", workflow_type=workflow_type)

        result = await self.llm.generate(
            task_type="multi_step_reasoning",
            prompt=APPROVAL_ROUTING_PROMPT.format(
                workflow_type=workflow_type,
                extracted_data=json.dumps(extracted_data, indent=2),
            ),
            system="You are an enterprise approval routing engine.",
            temperature=0.05,
            complexity=0.7,
        )

        try:
            parsed = json.loads(result["content"])
        except json.JSONDecodeError:
            content = result["content"]
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                parsed = json.loads(content[start:end])
            else:
                # Default: require approval for safety
                parsed = {
                    "approval_required": True,
                    "approver_role": "manager",
                    "reason": "Could not parse approval logic, defaulting to manager",
                }

        logger.info(
            "decision_approval_determined",
            approval_required=parsed.get("approval_required"),
            approver=parsed.get("approver_role"),
            tier=result["tier"],
        )

        return {
            **parsed,
            "llm_tier": result["tier"],
            "latency_ms": result["latency_ms"],
        }

    async def process(self, request_text: str) -> dict[str, Any]:
        """Full decision pipeline: classify → extract → route approval.

        Returns complete decision context for the orchestrator.
        """
        # Step 1: Classify
        classification = await self.classify(request_text)
        workflow_type = classification["category"]

        # Step 2: Extract slots
        slots = await self.extract_slots(request_text, workflow_type)

        # Step 3: Determine approval
        approval = await self.determine_approval(workflow_type, slots)

        return {
            "workflow_type": workflow_type,
            "classification": classification,
            "extracted_data": slots,
            "approval": approval,
            "decided_at": datetime.now(timezone.utc).isoformat(),
        }
