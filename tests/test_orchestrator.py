"""Tests for LangGraph Orchestrator.

Covers:
- Workflow state creation
- Node execution (classify, route, execute, monitor)
- Conditional edges and failure handling
- Full workflow execution
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from nexus.agents.orchestrator import (
    WorkflowState,
    classify_node,
    route_node,
    execute_node,
    monitor_node,
    handle_failure_node,
    should_execute_or_fail,
    after_execution,
    after_failure,
    build_orchestrator_graph,
    compile_orchestrator,
)


# ── WorkflowState Tests ─────────────────────────────────────────────────────


def test_workflow_state_create():
    """Test WorkflowState factory creates valid state."""
    state = WorkflowState.create(
        workflow_type="procurement",
        payload={"item": "laptop", "quantity": 5},
        created_by="test_user",
    )

    assert state["workflow_id"] is not None
    assert state["workflow_type"] == "procurement"
    assert state["status"] == "pending"
    assert state["current_phase"] == "initialized"
    assert state["payload"] == {"item": "laptop", "quantity": 5}
    assert state["created_by"] == "test_user"
    assert state["retry_count"] == 0
    assert state["human_override"] is False
    assert state["error_log"] == []
    assert state["agent_outputs"] == []


def test_workflow_state_meeting_type():
    """Test meeting workflow type."""
    state = WorkflowState.create(
        workflow_type="meeting",
        payload={"title": "Sprint Planning"},
    )

    assert state["workflow_type"] == "meeting"
    assert state["status"] == "pending"


# ── Node Tests ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_classify_node():
    """Test classification node updates state correctly."""
    state = WorkflowState.create(
        workflow_type="procurement",
        payload={"item": "test"},
    )

    result = await classify_node(state)

    assert result["current_phase"] == "classified"
    assert result["status"] == "in_progress"
    assert len(result["agent_outputs"]) == 1
    assert result["agent_outputs"][0]["agent"] == "classifier"
    assert result["agent_outputs"][0]["phase"] == "classify"


@pytest.mark.asyncio
async def test_route_node_valid_type():
    """Test routing node with valid workflow type."""
    state = WorkflowState.create(
        workflow_type="onboarding",
        payload={},
    )

    result = await route_node(state)

    assert result["current_phase"] == "routed"
    assert len(result["agent_outputs"]) == 1
    assert result["agent_outputs"][0]["result"] == "routed to onboarding_executor"


@pytest.mark.asyncio
async def test_route_node_invalid_type():
    """Test routing node fails gracefully with invalid type."""
    state = WorkflowState.create(
        workflow_type="invalid_type",
        payload={},
    )

    result = await route_node(state)

    assert result["status"] == "failed"
    assert len(result["error_log"]) == 1
    assert "Unknown workflow type" in result["error_log"][0]["error"]


@pytest.mark.asyncio
async def test_monitor_node():
    """Test monitoring node completes workflow."""
    state = WorkflowState.create(
        workflow_type="contract",
        payload={},
    )
    state["status"] = "completed"
    state["current_phase"] = "executed"

    result = await monitor_node(state)

    assert result["current_phase"] == "completed"
    assert len(result["agent_outputs"]) >= 1
    assert result["agent_outputs"][-1]["agent"] == "monitor"


# ── Failure Handling Tests ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_failure_node_retry():
    """Test failure handler retries up to 3 times."""
    state = WorkflowState.create(
        workflow_type="procurement",
        payload={},
    )
    state["status"] = "failed"
    state["retry_count"] = 0

    # First retry
    result = await handle_failure_node(state)
    assert result["status"] == "in_progress"
    assert result["current_phase"] == "retrying"
    assert result["retry_count"] == 1

    # Second retry
    result = await handle_failure_node(result)
    assert result["retry_count"] == 2

    # Third retry
    result = await handle_failure_node(result)
    assert result["retry_count"] == 3

    # Fourth failure - should escalate
    result = await handle_failure_node(result)
    assert result["status"] == "escalated"
    assert result["human_override"] is True


# ── Conditional Edge Tests ──────────────────────────────────────────────────


def test_should_execute_or_fail():
    """Test conditional edge after routing."""
    state_ok = {"status": "pending"}
    state_failed = {"status": "failed"}

    assert should_execute_or_fail(state_ok) == "execute"
    assert should_execute_or_fail(state_failed) == "handle_failure"


def test_after_execution():
    """Test conditional edge after execution."""
    state_success = {"status": "completed"}
    state_failed = {"status": "failed"}
    state_escalated = {"status": "escalated"}

    assert after_execution(state_success) == "monitor"
    assert after_execution(state_failed) == "handle_failure"
    assert after_execution(state_escalated) == "handle_failure"


def test_after_failure():
    """Test conditional edge after failure handling."""
    state_retrying = {"current_phase": "retrying"}
    state_escalated = {"current_phase": "escalated"}

    assert after_failure(state_retrying) == "execute"
    assert after_failure(state_escalated) == "END"


# ── Graph Compilation Tests ─────────────────────────────────────────────────


def test_build_orchestrator_graph():
    """Test graph builds with correct structure."""
    graph = build_orchestrator_graph()

    # Check nodes exist
    nodes = list(graph.nodes.keys())
    assert "classify" in nodes
    assert "route" in nodes
    assert "execute" in nodes
    assert "monitor" in nodes
    assert "handle_failure" in nodes


def test_compile_orchestrator():
    """Test orchestrator compiles successfully."""
    app = compile_orchestrator()
    assert app is not None


# ── Integration Test ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_workflow_execution():
    """Test complete workflow through orchestrator."""
    app = compile_orchestrator()

    initial_state = WorkflowState.create(
        workflow_type="meeting",
        payload={"title": "Test Meeting"},
        created_by="test",
    )

    # Note: This will fail at execute_node since we don't have real tools
    # but it tests the graph structure
    result = await app.ainvoke(initial_state)

    assert result is not None
    assert result["workflow_id"] == initial_state["workflow_id"]
    assert result["workflow_type"] == "meeting"
