"""Procurement Execution Agent — Full workflow implementation.

Flow: classify → extract → budget_check → create_po → send_approval
     → three_way_match → trigger_payment → complete

Uses SAP tool for PO/payment, Slack/Email for approvals.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import structlog

from nexus.llm.router import LLMRouter
from nexus.tools.registry import ToolRegistry
from nexus.memory.audit_logger import AuditLogger
from nexus.approvals.handler import ApprovalHandler

logger = structlog.get_logger()

BUDGET_THRESHOLDS = {
    "auto_approve": 5_000,       # < $5K auto-approved
    "manager_approve": 50_000,   # $5K–$50K manager
    "vp_approve": float("inf"),  # > $50K VP
}


class ProcurementAgent:
    """Executes procurement workflows: PO → approval → match → payment.

    Steps:
        1. Extract procurement details (item, qty, price, vendor)
        2. Budget check + approval routing
        3. Create PO in SAP
        4. Send approval notification (Slack + Email)
        5. 3-way match (PO ↔ Goods Receipt ↔ Invoice)
        6. Trigger payment via SAP FI
        7. Log completion
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        llm_router: LLMRouter,
        audit_logger: AuditLogger | None = None,
        db_session=None,
    ):
        self.tools = tool_registry
        self.llm = llm_router
        self.audit = audit_logger or AuditLogger()
        self.db = db_session

    async def execute(self, state: dict) -> dict[str, Any]:
        """Run the full procurement pipeline."""
        workflow_id = state.get("workflow_id", "unknown")
        payload = state.get("payload", {})

        logger.info("procurement_start", workflow_id=workflow_id)

        try:
            # Step 1: Extract procurement details
            extracted = await self._extract_details(payload)
            await self.audit.log_action(
                workflow_id=workflow_id,
                agent_name="procurement",
                action="extract_details",
                status="success",
                output_data=extracted,
            )

            # Step 2: Budget check + determine approval
            approval_info = self._determine_approval(extracted)
            await self.audit.log_action(
                workflow_id=workflow_id,
                agent_name="procurement",
                action="budget_check",
                status="success",
                output_data=approval_info,
            )

            # Step 3: Create PO in SAP
            po_result = await self._create_purchase_order(extracted)
            await self.audit.log_action(
                workflow_id=workflow_id,
                agent_name="procurement",
                action="create_po",
                status="success",
                output_data=po_result,
            )

            # Step 4: Send approval if needed
            if approval_info["approval_required"]:
                approval_result = await self._send_approval_request(
                    workflow_id, extracted, approval_info, po_result
                )
                await self.audit.log_action(
                    workflow_id=workflow_id,
                    agent_name="procurement",
                    action="approval_sent",
                    status="awaiting_approval",
                    output_data={
                        "approver": approval_info["approver_role"],
                        "approval_id": approval_result.get("approval_id"),
                    },
                )
                # Return to indicate workflow is waiting for approval
                return {
                    "agent": "procurement",
                    "status": "awaiting_approval",
                    "approval_id": approval_result.get("approval_id"),
                    "approver_role": approval_info["approver_role"],
                    "po_id": po_result.get("po_id"),
                    "message": "Workflow paused pending human approval",
                }

            # Step 5: 3-way match
            match_result = await self._three_way_match(po_result.get("po_id", ""))
            await self.audit.log_action(
                workflow_id=workflow_id,
                agent_name="procurement",
                action="three_way_match",
                status="success",
                output_data=match_result,
            )

            # Step 6: Trigger payment
            total = extracted.get("quantity", 1) * extracted.get("unit_price", 0)
            payment_result = await self._trigger_payment(
                po_result.get("po_id", ""),
                extracted.get("vendor", ""),
                total,
            )
            await self.audit.log_action(
                workflow_id=workflow_id,
                agent_name="procurement",
                action="payment_triggered",
                status="success",
                output_data=payment_result,
            )

            return {
                "agent": "procurement",
                "status": "completed",
                "po_id": po_result.get("po_id"),
                "total_amount": total,
                "approval": approval_info,
                "payment": payment_result,
                "steps_completed": 6,
            }

        except Exception as e:
            logger.error("procurement_failed", workflow_id=workflow_id, error=str(e))
            await self.audit.log_action(
                workflow_id=workflow_id,
                agent_name="procurement",
                action="execution_failed",
                status="failed",
                error_message=str(e),
            )
            raise

    async def _extract_details(self, payload: dict) -> dict:
        """Use LLM to extract structured procurement data."""
        request_text = payload.get("request_text", json.dumps(payload))

        result = await self.llm.generate(
            task_type="slot_filling",
            prompt=f"""Extract procurement details from this request:

{request_text}

Return JSON with: item, quantity, unit_price, total_budget, department, vendor, urgency
Only include fields that are mentioned or can be inferred.""",
            system="You are a procurement data extraction specialist.",
        )

        try:
            content = result["content"]
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(content[start:end])
        except (json.JSONDecodeError, ValueError):
            pass

        # Fallback: use payload directly
        return {
            "item": payload.get("item", "unknown"),
            "quantity": payload.get("quantity", 1),
            "unit_price": payload.get("unit_price", 0),
            "department": payload.get("department", "unknown"),
            "vendor": payload.get("vendor", ""),
            "urgency": payload.get("urgency", "normal"),
        }

    def _determine_approval(self, extracted: dict) -> dict:
        """Determine approval routing based on budget thresholds."""
        total = extracted.get("quantity", 1) * extracted.get("unit_price", 0)

        if total < BUDGET_THRESHOLDS["auto_approve"]:
            return {
                "approval_required": False,
                "approver_role": "auto",
                "reason": f"Amount ${total:,.2f} below auto-approve threshold",
                "total_amount": total,
            }
        elif total < BUDGET_THRESHOLDS["manager_approve"]:
            return {
                "approval_required": True,
                "approver_role": "manager",
                "reason": f"Amount ${total:,.2f} requires manager approval",
                "total_amount": total,
            }
        else:
            return {
                "approval_required": True,
                "approver_role": "vp",
                "reason": f"Amount ${total:,.2f} requires VP approval",
                "total_amount": total,
            }

    async def _create_purchase_order(self, extracted: dict) -> dict:
        """Create PO in SAP."""
        sap = self.tools.get("sap_erp")
        return await sap.call({
            "action": "create_po",
            "vendor_id": extracted.get("vendor", ""),
            "material": extracted.get("item", ""),
            "quantity": extracted.get("quantity", 1),
            "unit_price": extracted.get("unit_price", 0),
        })

    async def _send_approval_request(
        self, workflow_id: str, extracted: dict, approval: dict, po: dict
    ) -> dict:
        """Send approval via Slack and Email using ApprovalHandler."""
        from nexus.approvals.handler import ApprovalHandler

        total = approval.get("total_amount", 0)
        approver_role = approval.get("approver_role", "manager")

        # Use ApprovalHandler for database tracking + notifications
        if self.db:
            handler = ApprovalHandler(self.db, self.tools, self.audit)
            result = await handler.create_approval_request(
                workflow_id=workflow_id,
                workflow_type="procurement",
                approver_role=approver_role,
                amount=total,
                requestor=extracted.get("department", "unknown"),
                message=f"PO {po.get('po_id', 'N/A')}: {extracted.get('quantity', 0)}x {extracted.get('item', '')}",
                payload=extracted,
            )
            return result

        # Fallback: direct notification without DB tracking
        total = approval.get("total_amount", 0)
        result = {"slack": None, "email": None}

        if self.tools.has("slack_messenger"):
            slack = self.tools.get("slack_messenger")
            slack_result = await slack.call({
                "action": "send_approval",
                "workflow_id": workflow_id,
                "workflow_type": "procurement",
                "message": f"Purchase: {extracted.get('quantity', 0)}x {extracted.get('item', '')}",
                "amount": total,
                "requestor": extracted.get("department", "unknown"),
                "channel": f"#approvals-{approval['approver_role']}",
            })
            result["slack"] = slack_result

        if self.tools.has("email_connector"):
            email = self.tools.get("email_connector")
            email_result = await email.call({
                "action": "send_approval_email",
                "to": f"{approval['approver_role']}@company.com",
                "workflow_id": workflow_id,
                "workflow_type": "procurement",
                "message": f"PO {po.get('po_id', 'N/A')}: {extracted.get('item', '')}",
                "amount": total,
            })
            result["email"] = email_result

        return result

    async def _three_way_match(self, po_id: str) -> dict:
        """Run 3-way match in SAP."""
        sap = self.tools.get("sap_erp")
        return await sap.call({
            "action": "three_way_match",
            "po_id": po_id,
            "goods_receipt_id": f"GR-{po_id}",
            "invoice_id": f"INV-{po_id}",
        })

    async def _trigger_payment(self, po_id: str, vendor: str, amount: float) -> dict:
        """Trigger payment in SAP FI."""
        sap = self.tools.get("sap_erp")
        return await sap.call({
            "action": "trigger_payment",
            "po_id": po_id,
            "vendor_id": vendor,
            "amount": amount,
            "currency": "USD",
        })
