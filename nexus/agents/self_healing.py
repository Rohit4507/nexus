"""Self-Healing Agent + Circuit Breaker.

Handles transient errors (retry), data errors (request correction),
auth errors (credential refresh), and critical failures (escalation).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

logger = structlog.get_logger()


# ── Circuit Breaker ──────────────────────────────────────────────────────────

class CircuitOpenError(Exception):
    """Raised when circuit breaker is open."""
    pass


class CircuitBreaker:
    """Circuit breaker pattern for integration resilience.

    States:
        closed   → normal operation, tracking failures
        open     → all calls blocked, waiting for recovery timeout
        half_open → allowing one test call through
    """

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
    ):
        self.name = name
        self.failure_count: int = 0
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state: str = "closed"  # closed | open | half_open
        self.last_failure_time: float | None = None
        self.total_calls: int = 0
        self.total_failures: int = 0

    async def call(self, func, *args, **kwargs):
        """Execute function through the circuit breaker."""
        self.total_calls += 1

        if self.state == "open":
            elapsed = time.time() - (self.last_failure_time or 0)
            if elapsed > self.recovery_timeout:
                logger.info(
                    "circuit_half_open",
                    name=self.name,
                    elapsed_s=round(elapsed, 1),
                )
                self.state = "half_open"
            else:
                raise CircuitOpenError(
                    f"Circuit '{self.name}' is open. "
                    f"Retry after {self.recovery_timeout - elapsed:.0f}s"
                )

        try:
            result = await func(*args, **kwargs)
            # Success — reset
            if self.state == "half_open":
                logger.info("circuit_closed", name=self.name)
            self.failure_count = 0
            self.state = "closed"
            return result

        except Exception as e:
            self.failure_count += 1
            self.total_failures += 1
            self.last_failure_time = time.time()

            if self.failure_count >= self.failure_threshold:
                self.state = "open"
                logger.error(
                    "circuit_opened",
                    name=self.name,
                    failures=self.failure_count,
                    threshold=self.failure_threshold,
                )
            raise

    @property
    def health(self) -> dict:
        return {
            "name": self.name,
            "state": self.state,
            "failure_count": self.failure_count,
            "threshold": self.failure_threshold,
            "total_calls": self.total_calls,
            "total_failures": self.total_failures,
            "error_rate": (
                round(self.total_failures / self.total_calls, 3)
                if self.total_calls > 0 else 0.0
            ),
        }


# ── Error Classification ─────────────────────────────────────────────────────

@dataclass
class ClassifiedError:
    """Structured error with type classification."""
    original: Exception
    error_type: str  # transient | data | auth | logic | critical
    service: str = "unknown"
    field: str = ""
    message: str = ""

    @property
    def is_transient(self) -> bool:
        return self.error_type == "transient"

    @property
    def is_data_error(self) -> bool:
        return self.error_type == "data"

    @property
    def is_auth_error(self) -> bool:
        return self.error_type == "auth"

    @property
    def is_retriable(self) -> bool:
        return self.error_type in ("transient", "auth")


def classify_error(error: Exception, service: str = "unknown") -> ClassifiedError:
    """Classify an exception into an error type for self-healing."""
    msg = str(error).lower()

    # Transient — network, rate limits, timeouts
    transient_signals = ["timeout", "429", "503", "502", "connection", "temporary"]
    if any(s in msg for s in transient_signals):
        return ClassifiedError(
            original=error, error_type="transient",
            service=service, message=str(error),
        )

    # Auth — expired tokens, forbidden
    auth_signals = ["401", "403", "unauthorized", "forbidden", "token expired"]
    if any(s in msg for s in auth_signals):
        return ClassifiedError(
            original=error, error_type="auth",
            service=service, message=str(error),
        )

    # Data — validation, missing fields
    data_signals = ["validation", "missing", "required", "invalid", "not found"]
    if any(s in msg for s in data_signals):
        return ClassifiedError(
            original=error, error_type="data",
            service=service, message=str(error),
        )

    # Default — critical
    return ClassifiedError(
        original=error, error_type="critical",
        service=service, message=str(error),
    )


# ── Self-Healing Agent ───────────────────────────────────────────────────────

class SelfHealingAgent:
    """Handles workflow failures with retry, correction, and escalation.

    Strategy by error type:
        transient → exponential backoff (max 3 retries)
        data      → pause, request correction, notify requestor
        auth      → attempt credential refresh, then retry
        logic     → escalate to Decision Agent
        critical  → halt workflow, page on-call
    """

    MAX_RETRIES = 3
    BACKOFF_MULTIPLIER = 2
    INITIAL_BACKOFF_S = 1.0

    def __init__(self, audit_logger=None):
        self.audit_logger = audit_logger
        self._credential_cache: dict[str, str] = {}

    async def handle_failure(
        self,
        error: Exception,
        state: dict,
        service: str = "unknown",
    ) -> dict[str, Any]:
        """Main entry point — classify error and execute healing strategy.

        Returns:
            {"action": str, "state": dict, ...} with action being one of:
            retry, request_correction, escalated, halted
        """
        classified = classify_error(error, service)

        # Always audit BEFORE attempting recovery
        if self.audit_logger:
            await self.audit_logger.log_action(
                workflow_id=state.get("workflow_id"),
                agent_name="self_healing",
                action=f"handling_{classified.error_type}",
                status="in_progress",
                input_data={"error": str(error), "service": service},
            )

        logger.info(
            "self_healing_start",
            error_type=classified.error_type,
            service=service,
            retry_count=state.get("retry_count", 0),
        )

        # ── Transient: exponential backoff ────────────────────────
        if classified.is_transient and state.get("retry_count", 0) < self.MAX_RETRIES:
            delay = self.INITIAL_BACKOFF_S * (
                self.BACKOFF_MULTIPLIER ** state.get("retry_count", 0)
            )
            logger.info("self_healing_retry", delay_s=delay)
            await asyncio.sleep(delay)
            state["retry_count"] = state.get("retry_count", 0) + 1
            state["status"] = "in_progress"
            return {"action": "retry", "state": state, "delay_s": delay}

        # ── Data error: request correction ────────────────────────
        if classified.is_data_error:
            logger.warning("self_healing_data_error", field=classified.field)
            state["status"] = "awaiting_correction"
            return {
                "action": "request_correction",
                "state": state,
                "message": f"Data error: {classified.message}",
                "notify": ["requestor", "admin"],
            }

        # ── Auth error: try credential refresh ────────────────────
        if classified.is_auth_error:
            refreshed = await self._refresh_credentials(classified.service)
            if refreshed:
                state["retry_count"] = state.get("retry_count", 0) + 1
                state["status"] = "in_progress"
                return {"action": "retry", "state": state, "credential_refreshed": True}

        # ── All else: escalate ────────────────────────────────────
        logger.warning(
            "self_healing_escalate",
            error_type=classified.error_type,
            workflow_id=state.get("workflow_id"),
        )
        state["status"] = "escalated"
        state["human_override"] = True
        return {
            "action": "escalated",
            "state": state,
            "error_type": classified.error_type,
            "message": classified.message,
        }

    async def _refresh_credentials(self, service: str) -> bool:
        """Attempt to refresh credentials for a service.

        In production, this would call a secrets manager or OAuth refresh.
        """
        logger.info("credential_refresh_attempt", service=service)
        # Stub — in production, integrate with vault/OAuth
        return False
