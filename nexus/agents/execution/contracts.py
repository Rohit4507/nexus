"""Contract Lifecycle Execution Agent — Full workflow implementation.

Flow: extract → risk_analysis → draft_generation → legal_review_routing
     → docusign_envelope_creation → notify

Uses LLM Tier 2 (reasoning) for risk analysis, DocuSign for e-signatures,
and Slack/Email for legal review routing.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import structlog

from nexus.config import get_settings
from nexus.llm.router import LLMRouter
from nexus.tools.registry import ToolRegistry
from nexus.memory.audit_logger import AuditLogger
from nexus.memory.contract_type_aliases import canonical_contract_type

logger = structlog.get_logger()

LEGAL_REVIEW_AMOUNT_THRESHOLD = 100_000
# DocuSign REST envelope statuses that stop polling (lowercase match).
_TERMINAL_ENVELOPE_STATUSES = frozenset({
    "completed",
    "declined",
    "voided",
})


class ContractAgent:
    """Executes contract workflows: draft → review → sign → track.

    Steps:
        1. Extract contract terms and parties.
        2. Analyze text for risky clauses (Tier 2 LLM reasoning).
        3. Generate draft contract text.
        4. Route to Legal if amount threshold OR risk band OR LLM flags (any triggers).
        5. Create DocuSign envelope for signatures.
        6. Notify stakeholders; poll DocuSign until terminal signature status.
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        llm_router: LLMRouter,
        audit_logger: AuditLogger | None = None,
    ):
        self.tools = tool_registry
        self.llm = llm_router
        self.audit = audit_logger or AuditLogger()

    async def execute(self, state: dict) -> dict[str, Any]:
        """Run the full contract execution pipeline."""
        workflow_id = state.get("workflow_id", "unknown")
        payload = state.get("payload", {})

        logger.info("contract_execute_start", workflow_id=workflow_id)

        try:
            # Step 1: Extract contract details
            extracted = await self._extract_terms(payload)
            await self.audit.log_action(
                workflow_id=workflow_id,
                agent_name="contract",
                action="extract_terms",
                status="success",
                output_data=extracted,
            )

            # Step 2: Retrieve baseline policy clauses for draft grounding (FAISS)
            baseline_policy_context = await self._retrieve_policy_context(
                payload=payload,
                terms=extracted,
                mode="baseline",
            )
            await self.audit.log_action(
                workflow_id=workflow_id,
                agent_name="contract",
                action="policy_retrieval_baseline",
                status="success",
                output_data={
                    "hits": len(baseline_policy_context),
                    "metadata_filter": self._static_policy_metadata(
                        payload, extracted, "baseline", None
                    ),
                },
            )

            # Step 3: Risk analysis via LLM Tier 2
            risk_assessment = await self._analyze_risk(
                payload.get("contract_text", ""), extracted
            )
            await self.audit.log_action(
                workflow_id=workflow_id,
                agent_name="contract",
                action="risk_analysis",
                status="success",
                output_data=risk_assessment,
            )

            # Step 4: Retrieve mitigation clauses after risk analysis (FAISS)
            mitigation_policy_context = await self._retrieve_policy_context(
                payload=payload,
                terms=extracted,
                mode="mitigation",
                risk_assessment=risk_assessment,
            )
            await self.audit.log_action(
                workflow_id=workflow_id,
                agent_name="contract",
                action="policy_retrieval_mitigation",
                status="success",
                output_data={
                    "hits": len(mitigation_policy_context),
                    "metadata_filter": self._static_policy_metadata(
                        payload, extracted, "mitigation", risk_assessment
                    ),
                },
            )

            # Step 5: Draft generation
            draft_text = await self._generate_draft(
                extracted,
                risk_assessment,
                baseline_policy_context,
                mitigation_policy_context,
            )
            await self.audit.log_action(
                workflow_id=workflow_id,
                agent_name="contract",
                action="draft_generation",
                status="success",
                output_data={"draft_length": len(draft_text)},
            )

            # Step 6: Legal review routing
            review_status = await self._route_legal_review(
                workflow_id, extracted, risk_assessment
            )
            await self.audit.log_action(
                workflow_id=workflow_id,
                agent_name="contract",
                action="legal_review_routing",
                status="success" if not review_status.get("blocked") else "awaiting_review",
                output_data=review_status,
            )

            # Block pipeline if legal review is required
            if review_status.get("blocked"):
                logger.info("contract_blocked_for_legal", workflow_id=workflow_id)
                return {
                    "agent": "contract",
                    "status": "awaiting_human",
                    "reason": "Legal review required (amount threshold and/or risk / LLM flag)",
                    "risk_assessment": risk_assessment,
                    "legal_trigger_reasons": risk_assessment.get("legal_trigger_reasons", []),
                }

            # Step 7: DocuSign envelope creation
            envelope_result = await self._create_docusign_envelope(
                workflow_id, extracted, draft_text
            )
            await self.audit.log_action(
                workflow_id=workflow_id,
                agent_name="contract",
                action="docusign_creation",
                status="success",
                output_data=envelope_result,
            )

            # Step 8: Notify stakeholders
            await self._notify_stakeholders(workflow_id, extracted, envelope_result)
            signature_status = await self._track_signature_status(envelope_result)

            return {
                "agent": "contract",
                "status": "completed",
                "contract_details": extracted,
                "risk_assessment": risk_assessment,
                "envelope": envelope_result,
                "signature_status": signature_status,
                "policy_context": {
                    "baseline_hits": len(baseline_policy_context),
                    "mitigation_hits": len(mitigation_policy_context),
                    "baseline_metadata": self._static_policy_metadata(
                        payload, extracted, "baseline", None
                    ),
                    "mitigation_metadata": self._static_policy_metadata(
                        payload, extracted, "mitigation", risk_assessment
                    ),
                },
                "steps_completed": 8,
            }

        except Exception as e:
            logger.error("contract_failed", workflow_id=workflow_id, error=str(e))
            await self.audit.log_action(
                workflow_id=workflow_id,
                agent_name="contract",
                action="execution_failed",
                status="failed",
                error_message=str(e),
            )
            raise

    async def _extract_terms(self, payload: dict) -> dict:
        """Use LLM Tier 1 to extract structured agreement data."""
        request_text = payload.get("request_text", json.dumps(payload))

        result = await self.llm.generate(
            task_type="slot_filling",
            prompt=f"""Extract key contract terms from this request:

{request_text}

Return JSON with: party_a, party_b, contract_type, amount, effective_date, expiration_date, signers (list of objects with name, email), jurisdiction (string, e.g. US), policy_version (string, e.g. 1.0).""",
            system="You are an expert paralegal AI.",
        )

        try:
            content = result["content"]
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(content[start:end])
                data["contract_type"] = canonical_contract_type(
                    data.get("contract_type", payload.get("contract_type"))
                )
                return data
        except (json.JSONDecodeError, ValueError):
            pass

        return {
            "party_a": "Company",
            "party_b": payload.get("vendor", "Unknown"),
            "contract_type": canonical_contract_type(payload.get("contract_type", "NDA")),
            "amount": payload.get("amount", 0),
            "signers": payload.get("signers", []),
            "jurisdiction": payload.get("jurisdiction", "US"),
            "policy_version": payload.get("policy_version", "1.0"),
        }

    def _normalize_risk_assessment(self, terms: dict, risk: dict) -> dict:
        """Unify legal gate: any of amount threshold, risk band, or LLM flag triggers review."""
        amount = self._safe_float(terms.get("amount", 0))
        rl = str(risk.get("risk_level", "low")).strip().lower()
        if rl not in ("low", "medium", "high", "critical"):
            rl = "low"
        reasons: list[str] = []
        if amount >= LEGAL_REVIEW_AMOUNT_THRESHOLD:
            reasons.append("amount_threshold")
        if rl in ("medium", "high", "critical"):
            reasons.append("risk_level")
        if risk.get("requires_legal") is True:
            reasons.append("llm_requires_legal")
        out = dict(risk)
        out["risk_level"] = rl
        out["requires_legal"] = len(reasons) > 0
        out["legal_trigger_reasons"] = reasons
        return out

    async def _analyze_risk(self, contract_text: str, terms: dict) -> dict:
        """Use LLM Tier 2 (Reasoning) to evaluate liability and indemnification."""
        amount = self._safe_float(terms.get("amount", 0))
        if not contract_text:
            base = {
                "risk_level": "low" if amount < 50_000 else "medium",
                "flagged_clauses": [],
                "reasoning": "Standard contract parameters based on metadata.",
                "requires_legal": False,
            }
            return self._normalize_risk_assessment(terms, base)

        prompt = f"""Analyze the provided contract text for business and legal risk.
Pay special attention to:
1. Unlimited liability clauses
2. Asymmetric indemnification
3. Auto-renewal terms
4. Governing law jurisdiction

Contract text:
{contract_text[:3000]}...

Output JSON containing:
- risk_level: string (low, medium, high, critical)
- flagged_clauses: list of strings (quotes of dangerous text)
- reasoning: string
- requires_legal: boolean (true if medium/high/critical)"""

        # Force Tier 2 for chain-of-thought risk reasoning
        result = await self.llm.generate(
            task_type="contract_clause_analysis",
            prompt=prompt,
            system="You are a corporate legal analyst. Return strict JSON only.",
        )

        try:
            content = result["content"]
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                parsed = json.loads(content[start:end])
                return self._normalize_risk_assessment(terms, parsed)
        except Exception:
            pass

        fallback_level = "low" if amount < 50_000 else "medium"
        base = {
            "risk_level": fallback_level,
            "requires_legal": False,
            "flagged_clauses": [],
            "reasoning": "Fallback parsing.",
        }
        return self._normalize_risk_assessment(terms, base)

    @staticmethod
    def _safe_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    async def _generate_draft(
        self,
        terms: dict,
        risk_assessment: dict,
        baseline_policy_context: list[dict],
        mitigation_policy_context: list[dict],
    ) -> str:
        """Generate final contract text using standard templates."""
        baseline_snippets = self._format_policy_snippets(baseline_policy_context)
        mitigation_snippets = self._format_policy_snippets(mitigation_policy_context)
        return f"""
        MASTER SERVICES AGREEMENT
        
        This Agreement is entered into by {terms.get('party_a', 'Company')} 
        and {terms.get('party_b', 'Counterparty')} on {datetime.now(timezone.utc).strftime('%Y-%m-%d')}.
        
        Contract Type: {terms.get('contract_type')}
        Total Value: ${terms.get('amount')}
        
        [Baseline Policy Clauses]
        {baseline_snippets}
        
        [Risk Mitigation Clauses]
        {mitigation_snippets}
        
        Risk Assessed as: {risk_assessment.get('risk_level', 'unknown')}
        """

    @staticmethod
    def _format_policy_snippets(hits: list[dict], limit: int = 3) -> str:
        if not hits:
            return "No policy snippets retrieved."
        lines = []
        for hit in hits[:limit]:
            text = str(hit.get("text", "")).strip().replace("\n", " ")
            if text:
                lines.append(f"- {text[:220]}")
        return "\n".join(lines) if lines else "No policy snippets retrieved."

    @staticmethod
    def _static_policy_metadata(
        payload: dict,
        terms: dict,
        mode: str,
        risk_assessment: dict | None,
    ) -> dict[str, str]:
        """Five-key FAISS filter: doc_type, jurisdiction, contract_type, risk_tag, version."""
        jurisdiction = str(
            payload.get("jurisdiction")
            or terms.get("jurisdiction")
            or "US"
        ).strip()
        version = str(
            payload.get("policy_version")
            or terms.get("policy_version")
            or "1.0"
        ).strip()
        contract_type = canonical_contract_type(terms.get("contract_type", "general"))
        if mode == "baseline":
            doc_type = "policy_clause"
            risk_tag = "general"
        else:
            doc_type = "mitigation_playbook"
            rl = str((risk_assessment or {}).get("risk_level", "medium")).strip().lower()
            risk_tag = rl if rl in ("low", "medium", "high", "critical") else "medium"
        return {
            "doc_type": doc_type,
            "jurisdiction": jurisdiction,
            "contract_type": contract_type,
            "risk_tag": risk_tag,
            "version": version,
        }

    async def _retrieve_policy_context(
        self,
        payload: dict,
        terms: dict,
        mode: str,
        risk_assessment: dict | None = None,
    ) -> list[dict]:
        """Retrieve static policy clauses from FAISS for draft + mitigation (filtered by five keys)."""
        contract_type = canonical_contract_type(terms.get("contract_type", "contract"))
        counterparty = terms.get("party_b", "counterparty")

        query = f"{contract_type} standard clauses for {counterparty}"
        if mode == "mitigation":
            risk_level = (risk_assessment or {}).get("risk_level", "unknown")
            flagged = ", ".join((risk_assessment or {}).get("flagged_clauses", [])[:2])
            query = f"{contract_type} mitigation clauses for {risk_level} risk {flagged}".strip()

        metadata_filter = self._static_policy_metadata(payload, terms, mode, risk_assessment)

        try:
            from nexus.memory.vector import VectorMemoryManager

            memory = VectorMemoryManager()
            try:
                results = await memory.search_static(
                    query=query,
                    k=5,
                    metadata_filter=metadata_filter,
                )
                logger.info(
                    "contract_policy_context_loaded",
                    mode=mode,
                    hits=len(results),
                    metadata_filter=metadata_filter,
                )
                return results
            finally:
                await memory.close()
        except Exception as exc:
            logger.warning(
                "contract_policy_context_unavailable",
                mode=mode,
                query=query,
                error=str(exc),
            )
            return []

    async def _route_legal_review(
        self, workflow_id: str, terms: dict, risk: dict
    ) -> dict:
        """Notify Legal via Slack + email when any trigger fires (amount / risk / LLM)."""
        if not risk.get("requires_legal"):
            return {
                "blocked": False,
                "status": "approved_by_ai",
                "legal_trigger_reasons": risk.get("legal_trigger_reasons", []),
            }

        reasons = risk.get("legal_trigger_reasons") or []
        reason_text = ", ".join(reasons) if reasons else "policy"
        legal_email = get_settings().legal_notification_email

        if self.tools.has("slack_messenger"):
            slack = self.tools.get("slack_messenger")
            await slack.call({
                "action": "send_approval",
                "workflow_id": workflow_id,
                "workflow_type": "contract",
                "message": (
                    f"Legal review required for {terms.get('contract_type')} with {terms.get('party_b')} "
                    f"(risk: {str(risk.get('risk_level', '')).upper()}). "
                    f"*Triggers:* {reason_text}\n\n*Reasoning:* {risk.get('reasoning', '')}"
                ),
                "amount": terms.get("amount", 0),
                "requestor": "Contract AI Agent",
                "channel": "#legal-review",
            })

        if self.tools.has("email_connector"):
            email = self.tools.get("email_connector")
            await email.call({
                "action": "send_notification",
                "to": legal_email,
                "subject": f"[Legal review] {workflow_id} — {terms.get('contract_type', 'Contract')}",
                "message": (
                    f"Workflow {workflow_id} requires legal review before signing.\n"
                    f"Counterparty: {terms.get('party_b')}\n"
                    f"Amount: {terms.get('amount')}\n"
                    f"Triggers: {reason_text}\n\n"
                    f"Reasoning: {risk.get('reasoning', '')}"
                ),
            })

        return {
            "blocked": True,
            "status": "pending_legal_approval",
            "legal_trigger_reasons": reasons,
        }

    async def _create_docusign_envelope(
        self, workflow_id: str, terms: dict, draft_text: str
    ) -> dict:
        """Trigger DocuSign envelope generation."""
        signers = terms.get("signers", [])
        if not signers:
            signers = [{"name": "Signer 1", "email": "signer1@example.com"}]

        docusign = self.tools.get("docusign")
        return await docusign.call({
            "action": "create_envelope",
            "subject": f"Signature Required: {terms.get('contract_type')} with {terms.get('party_a')}",
            "signers": signers,
            "document_content": draft_text,
        })

    async def _track_signature_status(self, envelope: dict) -> dict:
        """Poll DocuSign until status is terminal or max attempts."""
        envelope_id = envelope.get("envelope_id")
        if not envelope_id or not self.tools.has("docusign"):
            return {"final_status": "unknown", "envelope_id": envelope_id, "poll_history": []}

        settings = get_settings()
        interval = settings.contract_docusign_poll_interval_seconds
        max_attempts = settings.contract_docusign_poll_max_attempts
        docusign = self.tools.get("docusign")
        history: list[dict[str, Any]] = []
        last: dict[str, Any] = {}

        for attempt in range(1, max_attempts + 1):
            last = await docusign.call({
                "action": "get_status",
                "envelope_id": envelope_id,
            })
            raw = str(last.get("status", "")).strip().lower()
            history.append({"attempt": attempt, "status": raw, "response": last})
            if raw in _TERMINAL_ENVELOPE_STATUSES:
                logger.info(
                    "docusign_terminal_status",
                    envelope_id=envelope_id,
                    status=raw,
                    attempt=attempt,
                )
                return {
                    "envelope_id": envelope_id,
                    "final_status": raw,
                    "last_response": last,
                    "attempts": attempt,
                    "poll_history": history,
                    "terminal": True,
                }
            if attempt < max_attempts:
                await asyncio.sleep(interval)

        logger.warning(
            "docusign_poll_max_attempts",
            envelope_id=envelope_id,
            attempts=max_attempts,
        )
        final_raw = str(last.get("status", "")).strip().lower()
        return {
            "envelope_id": envelope_id,
            "final_status": final_raw,
            "last_response": last,
            "attempts": max_attempts,
            "poll_history": history,
            "terminal": False,
            "reason": "max_attempts_reached",
        }

    async def _notify_stakeholders(
        self, workflow_id: str, terms: dict, envelope: dict
    ) -> None:
        """Notify team that signatures are out."""
        if self.tools.has("slack_messenger"):
            slack = self.tools.get("slack_messenger")
            await slack.call({
                "action": "send_message",
                "channel": "#contracts",
                "text": f"✍️ Contract draft sent via DocuSign to {terms.get('party_b')}.\nEnvelope ID: `{envelope.get('envelope_id')}`",
            })

        if self.tools.has("email_connector"):
            email = self.tools.get("email_connector")
            legal_email = get_settings().legal_notification_email
            await email.call({
                "action": "send_notification",
                "to": legal_email,
                "subject": f"Contract sent for signature: {terms.get('contract_type', 'Agreement')}",
                "message": (
                    f"Workflow {workflow_id} has dispatched a DocuSign envelope "
                    f"for {terms.get('party_b')} (envelope {envelope.get('envelope_id')})."
                ),
            })
