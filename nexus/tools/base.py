"""Base abstraction for all enterprise integration tools.

Every tool must implement execute() and health_check().
Circuit breaker is built-in — all calls go through it automatically.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

import structlog

from nexus.agents.self_healing import CircuitBreaker

logger = structlog.get_logger()


class EnterpriseTool(ABC):
    """Base class for all enterprise integrations.

    Features:
    - Circuit breaker wrapping all calls
    - Mock mode for staging environments
    - Structured logging on every call
    - Health check interface
    """

    name: str = "base_tool"
    description: str = "Base enterprise tool"

    def __init__(self, env: str = "production"):
        self.env = env
        self.mock_mode = env in ("staging", "development")
        self.circuit_breaker = CircuitBreaker(
            name=self.name,
            failure_threshold=5,
            recovery_timeout=60.0,
        )
        self._call_count: int = 0
        self._total_latency_ms: int = 0

    async def call(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute through circuit breaker with logging and metrics.

        This is the public interface — agents call tool.call(params).
        Subclasses implement _execute() and _mock_execute().
        """
        self._call_count += 1
        start = time.monotonic()

        logger.info(
            "tool_call_start",
            tool=self.name,
            action=params.get("action", "unknown"),
            mock_mode=self.mock_mode,
        )

        try:
            if self.mock_mode:
                result = await self.circuit_breaker.call(
                    self._mock_execute, params
                )
            else:
                result = await self.circuit_breaker.call(
                    self._execute, params
                )

            latency_ms = int((time.monotonic() - start) * 1000)
            self._total_latency_ms += latency_ms

            logger.info(
                "tool_call_success",
                tool=self.name,
                action=params.get("action", "unknown"),
                latency_ms=latency_ms,
            )

            return {
                **result,
                "_meta": {
                    "tool": self.name,
                    "mock_mode": self.mock_mode,
                    "latency_ms": latency_ms,
                },
            }

        except Exception as e:
            latency_ms = int((time.monotonic() - start) * 1000)
            logger.error(
                "tool_call_failed",
                tool=self.name,
                action=params.get("action", "unknown"),
                error=str(e),
                latency_ms=latency_ms,
            )
            raise

    @abstractmethod
    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        """Real implementation — called in production mode."""
        ...

    async def _mock_execute(self, params: dict[str, Any]) -> dict[str, Any]:
        """Mock implementation — called in staging/dev mode.

        Override in subclass for tool-specific mock behavior.
        Default: returns generic success.
        """
        return {
            "status": "mock_success",
            "tool": self.name,
            "action": params.get("action", "unknown"),
            "message": f"Mock response from {self.name}",
        }

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the integration is reachable and authenticated."""
        ...

    @property
    def metrics(self) -> dict[str, Any]:
        """Usage metrics for this tool."""
        return {
            "name": self.name,
            "env": self.env,
            "mock_mode": self.mock_mode,
            "call_count": self._call_count,
            "avg_latency_ms": (
                round(self._total_latency_ms / self._call_count)
                if self._call_count > 0 else 0
            ),
            "circuit_breaker": self.circuit_breaker.health,
        }
