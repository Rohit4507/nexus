"""Slack Integration Tool.

Handles: Sending messages, approval requests with interactive buttons,
         channel creation, and notification delivery.

Production: Calls Slack Web API with Bot Token.
Staging: Logs messages instead of sending.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from nexus.tools.base import EnterpriseTool

logger = structlog.get_logger()


class SlackTool(EnterpriseTool):
    name = "slack_messenger"
    description = "Slack: messages, approval requests, channel management, notifications"

    def __init__(self, bot_token: str = "", env: str = "production"):
        super().__init__(env=env)
        self.bot_token = bot_token
        self.http = httpx.AsyncClient(
            base_url="https://slack.com/api",
            headers={
                "Authorization": f"Bearer {bot_token}",
                "Content-Type": "application/json",
            },
            timeout=15.0,
        )

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        action = params.get("action")

        if action == "send_message":
            return await self._send_message(params)
        elif action == "send_approval":
            return await self._send_approval_request(params)
        elif action == "create_channel":
            return await self._create_channel(params)
        elif action == "send_alert":
            return await self._send_alert(params)
        else:
            raise ValueError(f"Unknown Slack action: {action}")

    async def _send_message(self, params: dict) -> dict:
        resp = await self.http.post("/chat.postMessage", json={
            "channel": params["channel"],
            "text": params.get("text", ""),
            "blocks": params.get("blocks"),
        })
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Slack API error: {data.get('error')}")
        return {"status": "sent", "ts": data.get("ts"), "channel": params["channel"]}

    async def _send_approval_request(self, params: dict) -> dict:
        """Send interactive approval message with Approve/Reject buttons."""
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Approval Required*\n{params.get('message', '')}",
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Workflow:*\n{params.get('workflow_id', 'N/A')}"},
                    {"type": "mrkdwn", "text": f"*Type:*\n{params.get('workflow_type', 'N/A')}"},
                    {"type": "mrkdwn", "text": f"*Amount:*\n${params.get('amount', 'N/A')}"},
                    {"type": "mrkdwn", "text": f"*Requestor:*\n{params.get('requestor', 'N/A')}"},
                ],
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✅ Approve"},
                        "style": "primary",
                        "action_id": f"approve_{params.get('workflow_id', '')}",
                        "value": params.get("workflow_id", ""),
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "❌ Reject"},
                        "style": "danger",
                        "action_id": f"reject_{params.get('workflow_id', '')}",
                        "value": params.get("workflow_id", ""),
                    },
                ],
            },
        ]

        return await self._send_message({
            "channel": params.get("channel", params.get("approver", "")),
            "text": f"Approval needed: {params.get('message', '')}",
            "blocks": blocks,
        })

    async def _create_channel(self, params: dict) -> dict:
        resp = await self.http.post("/conversations.create", json={
            "name": params["channel_name"],
            "is_private": params.get("private", False),
        })
        resp.raise_for_status()
        data = resp.json()
        return {"status": "created", "channel_id": data.get("channel", {}).get("id")}

    async def _send_alert(self, params: dict) -> dict:
        """Send formatted alert to #nexus-alerts channel."""
        severity = params.get("severity", "info")
        emoji = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}.get(severity, "📢")

        return await self._send_message({
            "channel": params.get("channel", "#nexus-alerts"),
            "text": f"{emoji} *[{severity.upper()}]* {params.get('message', '')}",
        })

    async def _mock_execute(self, params: dict[str, Any]) -> dict[str, Any]:
        action = params.get("action", "unknown")
        logger.info(
            "slack_mock",
            action=action,
            channel=params.get("channel", ""),
            message=params.get("text", params.get("message", ""))[:100],
        )
        return {
            "status": "mock_sent",
            "action": action,
            "ts": f"mock_{datetime.now(timezone.utc).timestamp()}",
            "channel": params.get("channel", "mock-channel"),
        }

    async def health_check(self) -> bool:
        if self.mock_mode:
            return True
        try:
            resp = await self.http.post("/auth.test")
            data = resp.json()
            return data.get("ok", False)
        except Exception:
            return False

    async def close(self):
        await self.http.aclose()
