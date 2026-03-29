"""Tool Registry — central registry for all enterprise integrations.

Manages tool lifecycle, health checks, and provides a unified lookup
interface for agents to discover and call tools.
"""

from __future__ import annotations

from typing import Any

import structlog

from nexus.tools.base import EnterpriseTool
from nexus.config import get_settings

logger = structlog.get_logger()


class ToolRegistry:
    """Central registry for all enterprise integration tools.

    Usage:
        registry = ToolRegistry.from_settings()
        sap = registry.get("sap_erp")
        result = await sap.call({"action": "create_po", ...})
    """

    def __init__(self):
        self._tools: dict[str, EnterpriseTool] = {}

    def register(self, tool: EnterpriseTool) -> None:
        """Register a tool instance."""
        if tool.name in self._tools:
            logger.warning("tool_already_registered", name=tool.name)
        self._tools[tool.name] = tool
        logger.info(
            "tool_registered",
            name=tool.name,
            env=tool.env,
            mock_mode=tool.mock_mode,
        )

    def get(self, name: str) -> EnterpriseTool:
        """Get a tool by name. Raises KeyError if not found."""
        if name not in self._tools:
            available = list(self._tools.keys())
            raise KeyError(
                f"Tool '{name}' not registered. Available: {available}"
            )
        return self._tools[name]

    def has(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    @property
    def tool_names(self) -> list[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    async def health_check_all(self) -> dict[str, dict[str, Any]]:
        """Run health checks on all registered tools.

        Returns:
            {"tool_name": {"healthy": bool, "mock_mode": bool, "metrics": {...}}}
        """
        results = {}
        for name, tool in self._tools.items():
            try:
                healthy = await tool.health_check()
                results[name] = {
                    "healthy": healthy,
                    "mock_mode": tool.mock_mode,
                    "metrics": tool.metrics,
                }
            except Exception as e:
                results[name] = {
                    "healthy": False,
                    "mock_mode": tool.mock_mode,
                    "error": str(e),
                }
                logger.error("health_check_failed", tool=name, error=str(e))

        healthy_count = sum(1 for r in results.values() if r["healthy"])
        total = len(results)
        logger.info(
            "health_check_complete",
            healthy=healthy_count,
            total=total,
        )

        return results

    async def close_all(self) -> None:
        """Close all tool HTTP clients on shutdown."""
        for name, tool in self._tools.items():
            if hasattr(tool, "close"):
                try:
                    await tool.close()
                    logger.info("tool_closed", name=name)
                except Exception as e:
                    logger.error("tool_close_failed", name=name, error=str(e))

    @classmethod
    def from_settings(cls) -> "ToolRegistry":
        """Create a fully configured registry from application settings.

        Reads env vars to determine mock vs production mode for each tool.
        """
        from nexus.tools.sap import SAPTool
        from nexus.tools.salesforce import SalesforceTool
        from nexus.tools.slack import SlackTool
        from nexus.tools.email import EmailTool
        from nexus.tools.docusign import DocuSignTool

        settings = get_settings()
        env = settings.env.value

        registry = cls()

        # SAP ERP
        registry.register(SAPTool(
            base_url=settings.sap_base_url or "https://sandbox.api.sap.com",
            env=env,
        ))

        # Salesforce CRM
        registry.register(SalesforceTool(
            instance_url=settings.salesforce_url or "https://test.salesforce.com",
            env=env,
        ))

        # Slack
        registry.register(SlackTool(
            bot_token=settings.slack_bot_token,
            env=env,
        ))

        # Email
        registry.register(EmailTool(
            smtp_host=settings.smtp_host,
            smtp_user=settings.smtp_user,
            smtp_password=settings.smtp_password,
            env=env,
        ))

        # DocuSign
        docusign_key = (
            settings.docusign_staging_key
            if settings.is_staging
            else settings.docusign_api_key
        )
        registry.register(DocuSignTool(
            api_key=docusign_key,
            env=env,
        ))

        logger.info(
            "tool_registry_initialized",
            tools=registry.tool_names,
            env=env,
        )

        return registry
