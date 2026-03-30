"""Tests for Tool Integration Layer.

Covers:
- Tool Registry (registration, lookup, health checks)
- SAP Tool (PO creation, payments, HR records)
- Slack Tool (messages, approvals)
- Email Tool (notifications)
- DocuSign Tool (envelopes, status)
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from nexus.tools.registry import ToolRegistry
from nexus.tools.sap import SAPTool
from nexus.tools.slack import SlackTool
from nexus.tools.email import EmailTool
from nexus.tools.docusign import DocuSignTool
from nexus.tools.base import EnterpriseTool


# ── Tool Registry Tests ────────────────────────────────────────────────────


def test_tool_registry_register_and_get():
    """Test tool registration and retrieval."""

    class MockTool(EnterpriseTool):
        name = "mock_tool"
        description = "Mock tool for testing"

        async def _execute(self, params):
            return {"status": "ok"}

    registry = ToolRegistry()
    tool = MockTool(env="development")

    registry.register(tool)

    assert registry.has("mock_tool")
    assert registry.get("mock_tool") == tool
    assert "mock_tool" in registry.tool_names


def test_tool_registry_get_raises():
    """Test getting unregistered tool raises KeyError."""
    registry = ToolRegistry()

    with pytest.raises(KeyError, match="Tool 'nonexistent' not registered"):
        registry.get("nonexistent")


def test_tool_registry_from_settings():
    """Test registry creation from settings."""
    registry = ToolRegistry.from_settings()

    # Should have all tools registered
    assert registry.has("sap_erp")
    assert registry.has("slack_messenger")
    assert registry.has("email_connector")
    assert registry.has("docusign")
    assert registry.has("salesforce")


@pytest.mark.asyncio
async def test_tool_registry_health_check():
    """Test health check returns status for all tools."""
    registry = ToolRegistry.from_settings()

    results = await registry.health_check_all()

    assert "sap_erp" in results
    assert "slack_messenger" in results
    assert results["sap_erp"]["mock_mode"] is True  # No real API key


# ── SAP Tool Tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sap_tool_create_po_mock():
    """Test SAP PO creation in mock mode."""
    sap = SAPTool(base_url="https://sandbox.api.sap.com", env="development")

    result = await sap.call({
        "action": "create_po",
        "vendor_id": "VENDOR-001",
        "material": "LAPTOP-001",
        "quantity": 5,
        "unit_price": 1200,
    })

    assert result["status"] == "created"
    assert "po_id" in result
    assert result["po_id"].startswith("PO-")


@pytest.mark.asyncio
async def test_sap_tool_three_way_match_mock():
    """Test SAP 3-way match in mock mode."""
    sap = SAPTool(base_url="https://sandbox.api.sap.com", env="development")

    result = await sap.call({
        "action": "three_way_match",
        "po_id": "PO-12345",
        "goods_receipt_id": "GR-12345",
        "invoice_id": "INV-12345",
    })

    assert result["status"] == "matched"
    assert result["match_result"]["PO_Match"] is True
    assert result["match_result"]["GR_Match"] is True


@pytest.mark.asyncio
async def test_sap_tool_trigger_payment_mock():
    """Test SAP payment trigger in mock mode."""
    sap = SAPTool(base_url="https://sandbox.api.sap.com", env="development")

    result = await sap.call({
        "action": "trigger_payment",
        "po_id": "PO-12345",
        "vendor_id": "VENDOR-001",
        "amount": 6000,
        "currency": "USD",
    })

    assert result["status"] == "payment_initiated"
    assert "PaymentID" in result["data"]


@pytest.mark.asyncio
async def test_sap_tool_create_hr_record_mock():
    """Test SAP HR record creation in mock mode."""
    sap = SAPTool(base_url="https://sandbox.api.sap.com", env="development")

    result = await sap.call({
        "action": "create_hr_record",
        "first_name": "John",
        "last_name": "Smith",
        "department": "Engineering",
        "role": "Software Engineer",
    })

    assert result["status"] == "hr_record_created"
    assert "EmployeeID" in result["data"]


# ── Slack Tool Tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_slack_tool_send_message_mock():
    """Test Slack message sending in mock mode."""
    slack = SlackTool(env="development")

    result = await slack.call({
        "action": "send_message",
        "channel": "#test",
        "text": "Hello, World!",
    })

    assert result["status"] == "mock_sent"
    assert result["channel"] == "#test"


@pytest.mark.asyncio
async def test_slack_tool_send_approval_mock():
    """Test Slack approval request in mock mode."""
    slack = SlackTool(env="development")

    result = await slack.call({
        "action": "send_approval",
        "workflow_id": "wf-123",
        "workflow_type": "procurement",
        "message": "Purchase request for 5 laptops",
        "amount": 6000,
        "requestor": "user@example.com",
        "channel": "#approvals-manager",
    })

    assert result["status"] == "mock_sent"
    assert result["action"] == "send_approval"


# ── Email Tool Tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_email_tool_send_mock():
    """Test email sending in mock mode."""
    email = EmailTool(env="development")

    result = await email.call({
        "action": "send_email",
        "to": "user@example.com",
        "subject": "Test Email",
        "body": "This is a test.",
    })

    assert result["status"] == "mock_sent"
    assert result["to"] == "mock@example.com"  # Mock mode returns mock address


@pytest.mark.asyncio
async def test_email_tool_send_approval_mock():
    """Test approval email in mock mode."""
    email = EmailTool(env="development")

    result = await email.call({
        "action": "send_approval_email",
        "to": "manager@example.com",
        "workflow_id": "wf-456",
        "workflow_type": "contract",
        "message": "Contract approval needed",
        "amount": 150000,
    })

    assert result["status"] == "mock_sent"


# ── DocuSign Tool Tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_docusign_tool_create_envelope_mock():
    """Test DocuSign envelope creation in mock mode."""
    docusign = DocuSignTool(env="development")

    result = await docusign.call({
        "action": "create_envelope",
        "subject": "Sign this NDA",
        "signers": [
            {"name": "John Doe", "email": "john@example.com"},
            {"name": "Jane Smith", "email": "jane@example.com"},
        ],
    })

    assert result["status"] == "created"
    assert "envelope_id" in result
    assert len(result["envelope_id"]) == 36  # UUID length


@pytest.mark.asyncio
async def test_docusign_tool_get_status_mock():
    """Test DocuSign status check in mock mode."""
    docusign = DocuSignTool(env="development")

    result = await docusign.call({
        "action": "get_status",
        "envelope_id": "test-envelope-123",
    })

    assert result["status"] == "completed"
    assert result["envelope_id"] == "test-envelope-123"


@pytest.mark.asyncio
async def test_docusign_tool_void_envelope_mock():
    """Test DocuSign envelope voiding in mock mode."""
    docusign = DocuSignTool(env="development")

    result = await docusign.call({
        "action": "void_envelope",
        "envelope_id": "test-envelope-456",
        "reason": "Customer requested changes",
    })

    assert result["status"] == "voided"


# ── Enterprise Tool Base Tests ─────────────────────────────────────────────


def test_enterprise_tool_mock_mode_detection():
    """Test mock mode is detected correctly."""
    # No API key = mock mode
    sap = SAPTool(base_url="https://sandbox.api.sap.com", env="development")
    assert sap.mock_mode is True

    # With API key = production mode (if not development env)
    sap_prod = SAPTool(base_url="https://api.sap.com", api_key="test-key", env="production")
    assert sap_prod.mock_mode is False


@pytest.mark.asyncio
async def test_enterprise_tool_call_logs():
    """Test tool calls are logged."""
    slack = SlackTool(env="development")

    with patch("nexus.tools.base.logger") as mock_logger:
        await slack.call({
            "action": "send_message",
            "channel": "#test",
            "text": "Test",
        })

        mock_logger.info.assert_called()
