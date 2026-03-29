"""Email Integration Tool (SMTP/IMAP).

Handles: Sending emails (notifications, approvals, PO documents),
         and optionally listening to inbox for triggers.

Production: Sends via SMTP with TLS.
Staging: Logs email content without sending.
"""

from __future__ import annotations

import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone
from typing import Any

import structlog

from nexus.tools.base import EnterpriseTool

logger = structlog.get_logger()


class EmailTool(EnterpriseTool):
    name = "email_connector"
    description = "Email: send notifications, approvals, documents via SMTP"

    def __init__(
        self,
        smtp_host: str = "localhost",
        smtp_port: int = 587,
        smtp_user: str = "",
        smtp_password: str = "",
        from_address: str = "nexus@company.com",
        env: str = "production",
    ):
        super().__init__(env=env)
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.from_address = from_address

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        action = params.get("action")

        if action == "send_email":
            return await self._send_email(params)
        elif action == "send_approval_email":
            return await self._send_approval_email(params)
        elif action == "send_notification":
            return await self._send_notification(params)
        else:
            raise ValueError(f"Unknown email action: {action}")

    async def _send_email(self, params: dict) -> dict:
        """Send a plain/HTML email via SMTP."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = params.get("subject", "NEXUS Notification")
        msg["From"] = self.from_address
        msg["To"] = params["to"]

        if params.get("html"):
            msg.attach(MIMEText(params["html"], "html"))
        else:
            msg.attach(MIMEText(params.get("body", ""), "plain"))

        # Send via SMTP with TLS
        context = ssl.create_default_context()
        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            server.starttls(context=context)
            if self.smtp_user:
                server.login(self.smtp_user, self.smtp_password)
            server.send_message(msg)

        logger.info("email_sent", to=params["to"], subject=msg["Subject"])
        return {
            "status": "sent",
            "to": params["to"],
            "subject": msg["Subject"],
            "sent_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _send_approval_email(self, params: dict) -> dict:
        """Send approval request email with action links."""
        workflow_id = params.get("workflow_id", "")
        base_url = params.get("base_url", "http://localhost:8000")

        html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <h2 style="color: #1a1a2e;">🔔 Approval Required — NEXUS</h2>
            <div style="background: #f5f5f5; padding: 20px; border-radius: 8px; margin: 16px 0;">
                <p><strong>Workflow:</strong> {workflow_id}</p>
                <p><strong>Type:</strong> {params.get('workflow_type', 'N/A')}</p>
                <p><strong>Details:</strong> {params.get('message', '')}</p>
                <p><strong>Amount:</strong> ${params.get('amount', 'N/A')}</p>
                <p><strong>Requested by:</strong> {params.get('requestor', 'N/A')}</p>
            </div>
            <div style="margin: 24px 0;">
                <a href="{base_url}/approvals/{workflow_id}/approve"
                   style="background: #2ecc71; color: white; padding: 12px 24px;
                          text-decoration: none; border-radius: 4px; margin-right: 12px;">
                    ✅ Approve
                </a>
                <a href="{base_url}/approvals/{workflow_id}/reject"
                   style="background: #e74c3c; color: white; padding: 12px 24px;
                          text-decoration: none; border-radius: 4px;">
                    ❌ Reject
                </a>
            </div>
            <p style="color: #666; font-size: 12px;">
                Sent by NEXUS Enterprise AI • {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
            </p>
        </div>
        """

        return await self._send_email({
            "to": params["to"],
            "subject": f"[NEXUS] Approval Required: {params.get('workflow_type', '')} — {workflow_id[:8]}",
            "html": html,
        })

    async def _send_notification(self, params: dict) -> dict:
        """Send a simple notification email."""
        return await self._send_email({
            "to": params["to"],
            "subject": f"[NEXUS] {params.get('subject', 'Notification')}",
            "body": params.get("message", ""),
        })

    async def _mock_execute(self, params: dict[str, Any]) -> dict[str, Any]:
        action = params.get("action", "unknown")
        logger.info(
            "email_mock",
            action=action,
            to=params.get("to", ""),
            subject=params.get("subject", ""),
        )
        return {
            "status": "mock_sent",
            "action": action,
            "to": params.get("to", "mock@example.com"),
            "sent_at": datetime.now(timezone.utc).isoformat(),
        }

    async def health_check(self) -> bool:
        if self.mock_mode:
            return True
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=5) as server:
                server.ehlo()
            return True
        except Exception:
            return False
