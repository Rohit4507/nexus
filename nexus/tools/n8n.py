"""n8n Outbound Integration — Trigger n8n workflows from NEXUS.

This module allows NEXUS agents to trigger n8n workflows for:
- SAP ERP operations (when native tool is mock mode)
- Salesforce CRM updates
- Slack/Email notifications (fallback)
- Custom business logic in n8n

Usage:
    n8n = N8nClient(base_url, auth_token)
    result = await n8n.trigger_workflow("procurement-approval", {"po_id": "123"})
"""

from __future__ import annotations

import httpx
import structlog
from typing import Any

logger = structlog.get_logger()


class N8nClient:
    """Client for triggering n8n workflows via webhook or API.

    Supports:
    - Webhook triggers (POST to n8n webhook URL)
    - API triggers (POST to /api/v1/workflow/{id}/execute)
    - OAuth2 and API key authentication
    """

    def __init__(
        self,
        base_url: str = "http://localhost:5678",
        auth_token: str | None = None,
        api_key: str | None = None,
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.auth_token = auth_token
        self.api_key = api_key
        self.timeout = timeout
        self.http = httpx.AsyncClient(timeout=timeout)

        # Headers for authentication
        self._headers = {}
        if auth_token:
            self._headers["Authorization"] = f"Bearer {auth_token}"
        if api_key:
            self._headers["X-N8N-API-KEY"] = api_key

    async def trigger_webhook(
        self,
        webhook_path: str,
        payload: dict[str, Any],
        method: str = "POST",
    ) -> dict[str, Any]:
        """Trigger an n8n webhook workflow.

        Args:
            webhook_path: The webhook path (e.g., "/webhook/procurement-approval")
            payload: Data to send to the webhook
            method: HTTP method (POST or GET)

        Returns:
            Webhook response from n8n
        """
        url = f"{self.base_url}{webhook_path}"

        try:
            if method.upper() == "GET":
                response = await self.http.get(
                    url,
                    params=payload,
                    headers=self._headers,
                )
            else:
                response = await self.http.post(
                    url,
                    json=payload,
                    headers=self._headers,
                )

            response.raise_for_status()

            # n8n webhooks typically return JSON or plain text
            try:
                return response.json()
            except httpx.JSONDecodeError:
                return {"raw_response": response.text}

        except httpx.HTTPStatusError as e:
            logger.error(
                "n8n_webhook_http_error",
                webhook=webhook_path,
                status=e.response.status_code,
                error=str(e),
            )
            raise
        except httpx.RequestError as e:
            logger.error(
                "n8n_webhook_request_error",
                webhook=webhook_path,
                error=str(e),
            )
            raise

    async def execute_workflow(
        self,
        workflow_id: str,
        payload: dict[str, Any] | None = None,
        wait_for_completion: bool = False,
    ) -> dict[str, Any]:
        """Execute an n8n workflow via API.

        Args:
            workflow_id: The n8n workflow ID
            payload: Optional data to pass to the workflow
            wait_for_completion: If True, wait for workflow to complete

        Returns:
            Execution result from n8n
        """
        # Build URL for workflow execution
        if wait_for_completion:
            url = f"{self.base_url}/api/v1/workflow/{workflow_id}/execute?wait=true"
        else:
            url = f"{self.base_url}/api/v1/workflow/{workflow_id}/execute"

        try:
            response = await self.http.post(
                url,
                json=payload or {},
                headers=self._headers,
            )
            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            logger.error(
                "n8n_workflow_execution_error",
                workflow_id=workflow_id,
                status=e.response.status_code,
                error=str(e),
            )
            raise
        except httpx.RequestError as e:
            logger.error(
                "n8n_workflow_request_error",
                workflow_id=workflow_id,
                error=str(e),
            )
            raise

    async def get_workflow_status(
        self,
        execution_id: str,
    ) -> dict[str, Any]:
        """Get status of a workflow execution.

        Args:
            execution_id: The n8n execution ID

        Returns:
            Execution status and data
        """
        url = f"{self.base_url}/api/v1/execution/{execution_id}"

        try:
            response = await self.http.get(
                url,
                headers=self._headers,
            )
            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            logger.error(
                "n8n_status_error",
                execution_id=execution_id,
                status=e.response.status_code,
                error=str(e),
            )
            raise
        except httpx.RequestError as e:
            logger.error(
                "n8n_status_request_error",
                execution_id=execution_id,
                error=str(e),
            )
            raise

    async def health_check(self) -> dict[str, Any]:
        """Check n8n instance health."""
        try:
            response = await self.http.get(
                f"{self.base_url}/healthz",
                headers=self._headers,
                timeout=5.0,
            )
            response.raise_for_status()
            return {"healthy": True, "status": response.status_code}
        except Exception as e:
            return {"healthy": False, "error": str(e)}

    async def close(self) -> None:
        """Close HTTP client."""
        await self.http.aclose()


# ── Pre-built Workflow Triggers ──────────────────────────────────────────────

class N8nWorkflowTriggers:
    """High-level workflow triggers for common n8n integrations."""

    def __init__(self, client: N8nClient):
        self.client = client

    async def trigger_procurement_approval(
        self,
        po_id: str,
        amount: float,
        requestor: str,
        approver_email: str,
    ) -> dict:
        """Trigger procurement approval workflow in n8n."""
        return await self.client.trigger_webhook(
            "/webhook/procurement-approval",
            {
                "po_id": po_id,
                "amount": amount,
                "requestor": requestor,
                "approver_email": approver_email,
                "source": "nexus",
            },
        )

    async def trigger_salesforce_update(
        self,
        object_type: str,  # "Contact", "Opportunity", "Account"
        record_id: str,
        field_updates: dict,
    ) -> dict:
        """Trigger Salesforce update workflow in n8n."""
        return await self.client.trigger_webhook(
            "/webhook/salesforce-update",
            {
                "object_type": object_type,
                "record_id": record_id,
                "field_updates": field_updates,
                "source": "nexus",
            },
        )

    async def trigger_slack_notification(
        self,
        channel: str,
        message: str,
        blocks: list | None = None,
    ) -> dict:
        """Trigger Slack notification via n8n."""
        return await self.client.trigger_webhook(
            "/webhook/slack-notify",
            {
                "channel": channel,
                "message": message,
                "blocks": blocks or [],
                "source": "nexus",
            },
        )

    async def trigger_email_send(
        self,
        to: str,
        subject: str,
        body: str,
        cc: list | None = None,
    ) -> dict:
        """Trigger email send via n8n."""
        return await self.client.trigger_webhook(
            "/webhook/email-send",
            {
                "to": to,
                "subject": subject,
                "body": body,
                "cc": cc or [],
                "source": "nexus",
            },
        )

    async def trigger_contract_generation(
        self,
        contract_type: str,
        counterparty: str,
        terms: dict,
    ) -> dict:
        """Trigger contract document generation in n8n."""
        return await self.client.trigger_webhook(
            "/webhook/contract-generation",
            {
                "contract_type": contract_type,
                "counterparty": counterparty,
                "terms": terms,
                "source": "nexus",
            },
        )


# ── Factory Function ─────────────────────────────────────────────────────────

def create_n8n_client_from_config() -> N8nClient:
    """Create n8n client from environment configuration."""
    from nexus.config import get_settings

    settings = get_settings()

    # Build n8n base URL from common patterns
    n8n_url = settings.n8n_url if hasattr(settings, "n8n_url") else "http://localhost:5678"

    return N8nClient(
        base_url=n8n_url,
        auth_token=settings.n8n_auth_token if hasattr(settings, "n8n_auth_token") else None,
        api_key=settings.n8n_api_key if hasattr(settings, "n8n_api_key") else None,
    )
