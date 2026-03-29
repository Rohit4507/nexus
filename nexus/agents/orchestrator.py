"""LangGraph Orchestrator — the brain of NEXUS.

Uses LangGraph 1.1.3 StateGraph to route workflows through:
  classify → route → execute → monitor → (handle_failure if needed)

Each node is an async function that receives and returns WorkflowState.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional, Annotated

import structlog
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages

from nexus.llm.router import LLMRouter
from nexus.tools.registry import ToolRegistry
from nexus.memory.audit_logger import AuditLogger

from nexus.agents.execution.procurement import ProcurementAgent
from nexus.agents.execution.onboarding import OnboardingAgent
from nexus.agents.execution.contracts import ContractAgent

logger = structlog.get_logger()


# ── Workflow State Schema ────────────────────────────────────────────────────

class WorkflowState(dict):
    """LangGraph state for workflow orchestration.

    Inherits from dict for LangGraph compatibility.
    Access fields via state["key"] or define typed helpers.
    """

    @staticmethod
    def create(
        workflow_type: str,
        payload: dict[str, Any],
        created_by: str | None = None,
    ) -> "WorkflowState":
        """Factory to create a new workflow state with defaults."""
        now = datetime.now(timezone.utc).isoformat()
        return WorkflowState(
            workflow_id=str(uuid.uuid4()),
            workflow_type=workflow_type,
            current_phase="initialized",
            status="pending",
            payload=payload,
            agent_outputs=[],
            error_log=[],
            sla_deadline=None,
            retry_count=0,
            human_override=False,
            llm_tier_used=None,
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )


# ── Graph Node Functions ─────────────────────────────────────────────────────

async def classify_node(state: dict) -> dict:
    """Classify the incoming request using Decision Agent (Tier 1).

    Sets: workflow_type confirmation, extracted slots, current_phase.
    """
    logger.info(
        "classify_start",
        workflow_id=state["workflow_id"],
        workflow_type=state["workflow_type"],
    )

    # Decision agent will be injected at runtime via config
    state["current_phase"] = "classifying"
    state["status"] = "in_progress"
    state["updated_at"] = datetime.now(timezone.utc).isoformat()

    # The actual LLM call happens in the decision agent
    # This node delegates to it and captures results
    state["agent_outputs"].append({
        "agent": "classifier",
        "phase": "classify",
        "timestamp": state["updated_at"],
        "result": f"classified as {state['workflow_type']}",
    })

    state["current_phase"] = "classified"
    return state


async def route_node(state: dict) -> dict:
    """Route to the appropriate execution agent based on workflow_type."""
    logger.info(
        "route_start",
        workflow_id=state["workflow_id"],
        workflow_type=state["workflow_type"],
    )

    state["current_phase"] = "routing"
    state["updated_at"] = datetime.now(timezone.utc).isoformat()

    # Routing logic — determines which execution path
    wf_type = state["workflow_type"]
    valid_types = {"procurement", "onboarding", "contract", "meeting"}

    if wf_type not in valid_types:
        state["status"] = "failed"
        state["error_log"].append({
            "phase": "routing",
            "error": f"Unknown workflow type: {wf_type}",
            "timestamp": state["updated_at"],
        })
        return state

    state["current_phase"] = "routed"
    state["agent_outputs"].append({
        "agent": "router",
        "phase": "route",
        "timestamp": state["updated_at"],
        "result": f"routed to {wf_type}_executor",
    })

    return state


async def execute_node(state: dict) -> dict:
    """Dispatch to the appropriate execution agent."""
    logger.info(
        "execute_start",
        workflow_id=state["workflow_id"],
        workflow_type=state["workflow_type"],
    )

    state["current_phase"] = "executing"
    state["updated_at"] = datetime.now(timezone.utc).isoformat()

    # Instantiate runtime dependencies
    tools = ToolRegistry.from_settings()
    llm = LLMRouter()
    audit = AuditLogger()

    wf_type = state["workflow_type"]
    result = {}

    try:
        if wf_type == "procurement":
            agent = ProcurementAgent(tools, llm, audit)
            result = await agent.execute(state)
        elif wf_type == "onboarding":
            agent = OnboardingAgent(tools, llm, audit)
            result = await agent.execute(state)
        elif wf_type == "contract":
            agent = ContractAgent(tools, llm, audit)
            result = await agent.execute(state)
        elif wf_type == "meeting":
            result = {"status": "mocked", "msg": "meeting agent stub"}
        else:
            raise ValueError(f"No execution logic for {wf_type}")

        state["agent_outputs"].append({
            "agent": f"{wf_type}_executor",
            "phase": "execute",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "result": result,
        })
        
        # Shutdown runtime clients properly
        await llm.close()
        await tools.close_all()

        if result.get("status") == "awaiting_human":
            state["status"] = "in_progress"
            state["human_override"] = True
        else:
            state["status"] = "completed"
        
        state["current_phase"] = "executed"

    except Exception as e:
        logger.error("execution_failed", error=str(e), workflow_type=wf_type)
        await llm.close()
        await tools.close_all()
        state["error_log"].append({
            "phase": "execute",
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        state["status"] = "failed"

    return state


async def monitor_node(state: dict) -> dict:
    """Post-execution monitoring — SLA check, audit log."""
    logger.info(
        "monitor_start",
        workflow_id=state["workflow_id"],
        status=state["status"],
    )

    state["current_phase"] = "monitoring"
    state["updated_at"] = datetime.now(timezone.utc).isoformat()

    state["agent_outputs"].append({
        "agent": "monitor",
        "phase": "monitor",
        "timestamp": state["updated_at"],
        "result": f"final_status={state['status']}",
    })

    state["current_phase"] = "completed"
    return state


async def handle_failure_node(state: dict) -> dict:
    """Handle failures — retry, escalate, or halt."""
    logger.warning(
        "failure_handler",
        workflow_id=state["workflow_id"],
        retry_count=state["retry_count"],
        errors=len(state["error_log"]),
    )

    state["current_phase"] = "handling_failure"
    state["updated_at"] = datetime.now(timezone.utc).isoformat()

    if state["retry_count"] < 3:
        state["retry_count"] += 1
        state["status"] = "in_progress"
        state["current_phase"] = "retrying"
        logger.info("retrying", attempt=state["retry_count"])
    else:
        state["status"] = "escalated"
        state["human_override"] = True
        state["current_phase"] = "escalated"
        logger.warning("escalated_to_human", workflow_id=state["workflow_id"])

    return state


# ── Conditional Edge Functions ───────────────────────────────────────────────

def should_execute_or_fail(state: dict) -> str:
    """After routing: execute if valid, handle failure if not."""
    if state["status"] == "failed":
        return "handle_failure"
    return "execute"


def after_execution(state: dict) -> str:
    """After execution: monitor if success, handle failure if not."""
    if state["status"] in ("failed", "escalated"):
        return "handle_failure"
    return "monitor"


def after_failure(state: dict) -> str:
    """After failure handling: retry (back to execute) or end."""
    if state["current_phase"] == "retrying":
        return "execute"
    return END


# ── Build the Graph ──────────────────────────────────────────────────────────

def build_orchestrator_graph() -> StateGraph:
    """Construct the LangGraph workflow orchestrator.

    Graph topology:
        START → classify → route → execute → monitor → END
                                ↘ handle_failure ↗ (retry loop)
    """
    graph = StateGraph(dict)

    # Register nodes
    graph.add_node("classify", classify_node)
    graph.add_node("route", route_node)
    graph.add_node("execute", execute_node)
    graph.add_node("monitor", monitor_node)
    graph.add_node("handle_failure", handle_failure_node)

    # Edges
    graph.add_edge(START, "classify")
    graph.add_edge("classify", "route")

    # Conditional: route → execute or handle_failure
    graph.add_conditional_edges(
        "route",
        should_execute_or_fail,
        {"execute": "execute", "handle_failure": "handle_failure"},
    )

    # Conditional: execute → monitor or handle_failure
    graph.add_conditional_edges(
        "execute",
        after_execution,
        {"monitor": "monitor", "handle_failure": "handle_failure"},
    )

    # monitor → END
    graph.add_edge("monitor", END)

    # Conditional: handle_failure → execute (retry) or END
    graph.add_conditional_edges(
        "handle_failure",
        after_failure,
        {"execute": "execute", END: END},
    )

    return graph


def compile_orchestrator():
    """Build and compile the orchestrator graph. Returns a runnable."""
    graph = build_orchestrator_graph()
    return graph.compile()


# ── Convenience runner ───────────────────────────────────────────────────────

async def run_workflow(
    workflow_type: str,
    payload: dict[str, Any],
    created_by: str | None = None,
) -> dict:
    """Run a workflow through the full orchestrator pipeline.

    Args:
        workflow_type: One of procurement, onboarding, contract, meeting
        payload: Workflow-specific data
        created_by: User/system that triggered this

    Returns:
        Final workflow state dict.
    """
    app = compile_orchestrator()
    initial_state = WorkflowState.create(
        workflow_type=workflow_type,
        payload=payload,
        created_by=created_by,
    )

    logger.info(
        "workflow_started",
        workflow_id=initial_state["workflow_id"],
        workflow_type=workflow_type,
    )

    result = await app.ainvoke(initial_state)

    logger.info(
        "workflow_finished",
        workflow_id=result["workflow_id"],
        status=result["status"],
        phases=len(result["agent_outputs"]),
    )

    return result
