"""Onboarding Execution Agent — stub for Phase 4.

Will handle: IT provisioning, HR records, training, equipment ordering.
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger()


class OnboardingAgent:
    """Executes onboarding workflows: accounts → training → HR → equipment."""

    def __init__(self, tool_registry=None, llm_router=None):
        self.tools = tool_registry
        self.llm = llm_router

    async def execute(self, state: dict) -> dict[str, Any]:
        logger.info(
            "onboarding_execute",
            workflow_id=state.get("workflow_id"),
            phase="stub",
        )
        return {
            "agent": "onboarding",
            "status": "stub_completed",
            "message": "Onboarding execution agent not yet implemented",
        }
