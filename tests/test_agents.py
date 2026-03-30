"""Tests for Agent Layer.

Covers:
- Decision Agent (classification, slot extraction, approval routing)
- Monitoring Agent (SLA checks, system health)
- Execution Agents (procurement, onboarding, contract)
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from nexus.agents.decision import DecisionAgent
from nexus.agents.monitoring import MonitoringAgent, SLA_CONFIG
from nexus.agents.sla_monitor import _check_all_active_workflows


# ── Decision Agent Tests ────────────────────────────────────────────────────


class MockLLMRouter:
    """Mock LLM router for testing."""

    async def generate(self, task_type: str, prompt: str, system: str = "", **kwargs):
        """Mock LLM generation."""
        if task_type == "intent_classification":
            content = '{"category": "procurement", "confidence": 0.95, "reasoning": "Clear purchase request"}'
        elif task_type == "slot_filling":
            content = '{"item": "laptop", "quantity": 5, "unit_price": 1200, "department": "engineering"}'
        elif task_type == "multi_step_reasoning":
            content = '{"approval_required": true, "approver_role": "manager", "reason": "Amount exceeds auto-approve threshold"}'
        else:
            content = "{}"

        return {
            "content": content,
            "tier": "tier1",
            "latency_ms": 150,
        }


@pytest.mark.asyncio
async def test_decision_agent_classify():
    """Test decision agent classifies requests correctly."""
    llm = MockLLMRouter()
    agent = DecisionAgent(llm)

    result = await agent.classify("I need to order 5 laptops for the engineering team")

    assert result["category"] == "procurement"
    assert result["confidence"] == 0.95
    assert result["llm_tier"] == "tier1"


@pytest.mark.asyncio
async def test_decision_agent_extract_slots():
    """Test slot extraction from request."""
    llm = MockLLMRouter()
    agent = DecisionAgent(llm)

    result = await agent.extract_slots(
        "Order 5 laptops at $1200 each for engineering",
        "procurement"
    )

    assert "item" in result
    assert "quantity" in result
    assert result.get("item") == "laptop"
    assert result.get("quantity") == 5


@pytest.mark.asyncio
async def test_decision_agent_full_pipeline():
    """Test full decision pipeline: classify → extract → route."""
    llm = MockLLMRouter()
    agent = DecisionAgent(llm)

    result = await agent.process("Need to order 5 laptops for engineering")

    assert result["workflow_type"] == "procurement"
    assert "classification" in result
    assert "extracted_data" in result
    assert "approval" in result
    assert "decided_at" in result


# ── Monitoring Agent Tests ──────────────────────────────────────────────────


class FakeAuditLogger:
    """Mock audit logger for testing."""

    async def log_action(self, **kwargs):
        return None


@pytest.mark.asyncio
async def test_monitoring_agent_sla_ok():
    """Test SLA check for workflow within bounds."""
    monitor = MonitoringAgent(db_session=None, audit_logger=FakeAuditLogger())

    now = datetime.now(timezone.utc)
    workflow = {
        "workflow_id": "test-123",
        "workflow_type": "procurement",
        "created_at": now - timedelta(minutes=1),  # Just 1 minute old
    }

    result = await monitor.check_sla(workflow)

    assert result["status"] == "ok"
    assert result["ratio"] < 0.1  # Less than 10% of SLA elapsed


@pytest.mark.asyncio
async def test_monitoring_agent_sla_warning():
    """Test SLA check triggers warning at 80% threshold."""
    monitor = MonitoringAgent(db_session=None, audit_logger=FakeAuditLogger())

    # Create workflow at 85% of SLA (procurement end_to_end = 3600s)
    now = datetime.now(timezone.utc)
    workflow = {
        "workflow_id": "test-456",
        "workflow_type": "procurement",
        "created_at": now - timedelta(seconds=3060),  # 85% of 3600s
    }

    result = await monitor.check_sla(workflow)

    assert result["status"] == "warning"
    assert result["ratio"] >= 0.8


@pytest.mark.asyncio
async def test_monitoring_agent_sla_breached():
    """Test SLA breach detection."""
    monitor = MonitoringAgent(db_session=None, audit_logger=FakeAuditLogger())

    # Create workflow past SLA deadline
    now = datetime.now(timezone.utc)
    workflow = {
        "workflow_id": "test-789",
        "workflow_type": "procurement",
        "created_at": now - timedelta(hours=2),  # 2 hours, SLA is 1 hour
    }

    result = await monitor.check_sla(workflow)

    assert result["status"] == "breached"
    assert result["severity"] == "critical"
    assert result["ratio"] > 1.0


@pytest.mark.asyncio
async def test_monitoring_agent_unknown_workflow_type():
    """Test monitoring handles unknown workflow types."""
    monitor = MonitoringAgent(db_session=None, audit_logger=FakeAuditLogger())

    workflow = {
        "workflow_id": "test-unknown",
        "workflow_type": "unknown_type",
        "created_at": datetime.now(timezone.utc),
    }

    result = await monitor.check_sla(workflow)

    assert result["status"] == "unknown"
    assert "No SLA config" in result.get("reason", "")


@pytest.mark.asyncio
async def test_monitoring_agent_system_health():
    """Test system health aggregation."""
    monitor = MonitoringAgent()

    result = await monitor.get_system_health()

    assert "timestamp" in result
    assert "agents" in result
    assert "sla_summary" in result
    assert result["agents"]["orchestrator"] == "healthy"


# ── SLA Config Tests ────────────────────────────────────────────────────────


def test_sla_config_structure():
    """Test SLA config has expected structure."""
    assert "procurement" in SLA_CONFIG
    assert "onboarding" in SLA_CONFIG
    assert "contract" in SLA_CONFIG
    assert "meeting" in SLA_CONFIG

    for workflow_type, phases in SLA_CONFIG.items():
        assert "end_to_end" in phases
        assert "target_seconds" in phases["end_to_end"]
        assert "escalation_at" in phases["end_to_end"]


def test_sla_thresholds():
    """Test SLA escalation thresholds are reasonable."""
    for workflow_type, phases in SLA_CONFIG.items():
        for phase_name, config in phases.items():
            threshold = config.get("escalation_at", 0)
            assert 0 < threshold <= 1.0, f"{workflow_type}.{phase_name} has invalid threshold"


def test_sla_procurement_targets():
    """Test procurement SLA targets are reasonable."""
    proc = SLA_CONFIG["procurement"]

    # Classification should be fast (< 1 min)
    assert proc["classification"]["target_seconds"] <= 60

    # End-to-end should be < 2 hours for simple procurement
    assert proc["end_to_end"]["target_seconds"] <= 7200


def test_sla_contract_targets():
    """Test contract SLA targets account for legal review."""
    contract = SLA_CONFIG["contract"]

    # Legal review can take up to 48 hours
    assert contract["legal_review"]["target_seconds"] <= 172800  # 48 hours

    # End-to-end can be up to a week
    assert contract["end_to_end"]["target_seconds"] <= 604800  # 7 days
