"""SAP ERP Integration Tool.

Handles: Purchase Orders (MM), Payments (FI), HR Records (HCM),
         Goods Receipts, Invoice Verification, 3-Way Matching.

Production: Calls SAP REST/OData APIs.
Staging: Returns realistic mock responses.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from nexus.tools.base import EnterpriseTool

logger = structlog.get_logger()


class SAPTool(EnterpriseTool):
    name = "sap_erp"
    description = "SAP ERP: purchase orders, payments, HR records, goods receipts"

    def __init__(self, base_url: str, api_key: str = "", env: str = "production"):
        super().__init__(env=env)
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.http = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=30.0,
        )

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        """Real SAP API calls."""
        action = params.get("action")

        if action == "create_po":
            return await self._create_purchase_order(params)
        elif action == "get_po":
            return await self._get_purchase_order(params["po_id"])
        elif action == "three_way_match":
            return await self._three_way_match(params)
        elif action == "trigger_payment":
            return await self._trigger_payment(params)
        elif action == "create_hr_record":
            return await self._create_hr_record(params)
        elif action == "goods_receipt":
            return await self._goods_receipt(params)
        else:
            raise ValueError(f"Unknown SAP action: {action}")

    async def _create_purchase_order(self, params: dict) -> dict:
        resp = await self.http.post(
            "/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrder",
            json={
                "CompanyCode": params.get("company_code", "1000"),
                "PurchaseOrderType": "NB",
                "Supplier": params.get("vendor_id", ""),
                "PurchasingOrganization": params.get("purchasing_org", "1000"),
                "PurchasingGroup": params.get("purchasing_group", "001"),
                "to_PurchaseOrderItem": [{
                    "Material": params.get("material", ""),
                    "OrderQuantity": str(params.get("quantity", 1)),
                    "NetPriceAmount": str(params.get("unit_price", 0)),
                    "Plant": params.get("plant", "1000"),
                }],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return {"status": "created", "po_id": data.get("PurchaseOrder", ""), "data": data}

    async def _get_purchase_order(self, po_id: str) -> dict:
        resp = await self.http.get(
            f"/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrder('{po_id}')"
        )
        resp.raise_for_status()
        return {"status": "found", "po_id": po_id, "data": resp.json()}

    async def _three_way_match(self, params: dict) -> dict:
        po_id = params["po_id"]
        gr_id = params.get("goods_receipt_id", "")
        inv_id = params.get("invoice_id", "")
        resp = await self.http.post(
            "/sap/opu/odata/sap/API_SUPPLIERINVOICE_PROCESS_SRV/Match",
            json={"PurchaseOrder": po_id, "GoodsReceipt": gr_id, "Invoice": inv_id},
        )
        resp.raise_for_status()
        return {"status": "matched", "match_result": resp.json()}

    async def _trigger_payment(self, params: dict) -> dict:
        resp = await self.http.post(
            "/sap/opu/odata/sap/API_PAYMENTRUN/A_PaymentRun",
            json={
                "PaymentMethod": params.get("payment_method", "T"),
                "Payee": params.get("vendor_id", ""),
                "Amount": str(params.get("amount", 0)),
                "Currency": params.get("currency", "USD"),
            },
        )
        resp.raise_for_status()
        return {"status": "payment_initiated", "data": resp.json()}

    async def _create_hr_record(self, params: dict) -> dict:
        resp = await self.http.post(
            "/sap/opu/odata/sap/API_BUSINESS_PARTNER/A_BusinessPartner",
            json={
                "FirstName": params.get("first_name", ""),
                "LastName": params.get("last_name", ""),
                "Department": params.get("department", ""),
                "JobTitle": params.get("role", ""),
            },
        )
        resp.raise_for_status()
        return {"status": "hr_record_created", "data": resp.json()}

    async def _goods_receipt(self, params: dict) -> dict:
        resp = await self.http.post(
            "/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV/A_MaterialDocumentHeader",
            json={
                "GoodsMovementCode": "01",
                "PurchaseOrder": params.get("po_id", ""),
                "Quantity": str(params.get("quantity", 1)),
            },
        )
        resp.raise_for_status()
        return {"status": "goods_received", "data": resp.json()}

    async def _mock_execute(self, params: dict[str, Any]) -> dict[str, Any]:
        """Realistic SAP mock responses."""
        action = params.get("action", "unknown")
        mock_po_id = f"PO-{uuid.uuid4().hex[:8].upper()}"

        mocks = {
            "create_po": {
                "status": "created",
                "po_id": mock_po_id,
                "data": {
                    "PurchaseOrder": mock_po_id,
                    "CompanyCode": "1000",
                    "Supplier": params.get("vendor_id", "VENDOR-001"),
                    "TotalAmount": params.get("quantity", 1) * params.get("unit_price", 0),
                    "Currency": "USD",
                    "CreatedAt": datetime.now(timezone.utc).isoformat(),
                },
            },
            "get_po": {
                "status": "found",
                "po_id": params.get("po_id", mock_po_id),
                "data": {"Status": "Released", "TotalAmount": "75000.00"},
            },
            "three_way_match": {
                "status": "matched",
                "match_result": {
                    "PO_Match": True, "GR_Match": True, "Invoice_Match": True,
                    "Discrepancies": [],
                },
            },
            "trigger_payment": {
                "status": "payment_initiated",
                "data": {
                    "PaymentID": f"PAY-{uuid.uuid4().hex[:8].upper()}",
                    "Amount": params.get("amount", 0),
                    "Status": "Scheduled",
                },
            },
            "create_hr_record": {
                "status": "hr_record_created",
                "data": {
                    "EmployeeID": f"EMP-{uuid.uuid4().hex[:6].upper()}",
                    "Name": f"{params.get('first_name', '')} {params.get('last_name', '')}",
                },
            },
            "goods_receipt": {
                "status": "goods_received",
                "data": {
                    "MaterialDocument": f"GR-{uuid.uuid4().hex[:8].upper()}",
                    "Quantity": params.get("quantity", 1),
                },
            },
        }

        return mocks.get(action, {"status": "mock_success", "action": action})

    async def health_check(self) -> bool:
        if self.mock_mode:
            return True
        try:
            resp = await self.http.get("/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/")
            return resp.status_code < 500
        except Exception:
            return False

    async def close(self):
        await self.http.aclose()
