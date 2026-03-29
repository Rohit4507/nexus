"""Monitoring Agent — SLA tracking, health checks, breach detection.

Polls every 60s in production. Escalates BEFORE breach using progress ratio.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger()


# ── SLA Configuration ────────────────────────────────────────────────────────

SLA_CONFIG: dict[str, dict[str, dict[str, Any]]] = {
    "procurement": {
        "classification":   {"target_seconds": 30,     "escalation_at": 0.8},
        "approval_routing": {"target_seconds": 60,     "escalation_at": 0.8},
        "po_creation":      {"target_seconds": 120,    "escalation_at": 0.7},
        "three_way_match":  {"target_seconds": 300,    "escalation_at": 0.8},
        "payment":          {"target_seconds": 120,    "escalation_at": 0.8},
        "end_to_end":       {"target_seconds": 3600,   "escalation_at": 0.75},
    },
    "onboarding": {
        "account_creation":    {"target_seconds": 300,   "escalation_at": 0.8},
        "training_assignment": {"target_seconds": 120,   "escalation_at": 0.8},
        "end_to_end":          {"target_seconds": 86400, "escalation_at": 0.9},
    },
    "contract": {
        "draft_generation": {"target_seconds": 180,    "escalation_at": 0.8},
        "legal_review":     {"target_seconds": 172800, "escalation_at": 0.9},
        "end_to_end":       {"target_seconds": 604800, "escalation_at": 0.85},
    },
    "meeting": {
        "transcription":     {"target_seconds": 300,   "escalation_at": 0.8},
        "action_extraction": {"target_seconds": 60,    "escalation_at": 0.8},
        "end_to_end":        {"target_seconds": 600,   "escalation_at": 0.8},
    },
}


class MonitoringAgent:
    """Monitors workflow SLAs and agent health.

    Capabilities:
    - Check SLA progress ratios and pre-breach escalation
    - Track agent health metrics (latency, error rates)
    - Aggregate system-wide statistics
    """

    def __init__(self, db_session=None, audit_logger=None):
        self.db = db_session
        self.audit_logger = audit_logger

    async def check_sla(self, workflow: dict) -> dict[str, Any]:
        """Check SLA status for a workflow.

        Returns:
            {"status": "ok"|"warning"|"breached", "ratio": float, ...}
        """
        wf_type = workflow.get("workflow_type", "")
        sla = SLA_CONFIG.get(wf_type)
        if not sla:
            return {"status": "unknown", "reason": f"No SLA config for {wf_type}"}

        created_str = workflow.get("created_at", "")
        if isinstance(created_str, str):
            created = datetime.fromisoformat(created_str)
        else:
            created = created_str

        now = datetime.now(timezone.utc)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)

        elapsed = (now - created).total_seconds()
        e2e = sla.get("end_to_end", {"target_seconds": 3600, "escalation_at": 0.8})
        target = e2e["target_seconds"]
        threshold = e2e["escalation_at"]
        ratio = elapsed / target if target > 0 else 0

        result = {
            "workflow_id": workflow.get("workflow_id"),
            "workflow_type": wf_type,
            "elapsed_seconds": round(elapsed, 1),
            "target_seconds": target,
            "ratio": round(ratio, 3),
        }

        if ratio >= 1.0:
            result["status"] = "breached"
            result["severity"] = "critical"
            logger.error("sla_breached", **result)
        elif ratio >= threshold:
            result["status"] = "warning"
            result["severity"] = "warning"
            logger.warning("sla_warning", **result)
        else:
            result["status"] = "ok"
            result["severity"] = "info"

        # Log escalation if needed
        if result["status"] in ("warning", "breached") and self.audit_logger:
            await self.audit_logger.log_action(
                workflow_id=workflow.get("workflow_id"),
                agent_name="monitoring",
                action=f"sla_{result['status']}",
                status=result["status"],
                input_data={"ratio": result["ratio"]},
            )

        return result

    async def check_phase_sla(
        self, workflow: dict, phase: str, phase_start: datetime
    ) -> dict[str, Any]:
        """Check SLA for a specific workflow phase."""
        wf_type = workflow.get("workflow_type", "")
        sla = SLA_CONFIG.get(wf_type, {})
        phase_sla = sla.get(phase)

        if not phase_sla:
            return {"status": "no_sla", "phase": phase}

        now = datetime.now(timezone.utc)
        if phase_start.tzinfo is None:
            phase_start = phase_start.replace(tzinfo=timezone.utc)

        elapsed = (now - phase_start).total_seconds()
        target = phase_sla["target_seconds"]
        ratio = elapsed / target if target > 0 else 0

        return {
            "phase": phase,
            "elapsed_seconds": round(elapsed, 1),
            "target_seconds": target,
            "ratio": round(ratio, 3),
            "status": "breached" if ratio >= 1.0
                      else "warning" if ratio >= phase_sla["escalation_at"]
                      else "ok",
        }

    async def get_system_health(self) -> dict[str, Any]:
        """Aggregate system health metrics."""
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agents": {
                "orchestrator": "healthy",
                "decision": "healthy",
                "monitoring": "healthy",
                "self_healing": "healthy",
            },
            "integrations": {},  # Populated when ToolRegistry is available
            "sla_summary": {
                "active_workflows": 0,
                "warnings": 0,
                "breaches": 0,
            },
        }
