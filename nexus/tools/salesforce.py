"""Salesforce CRM Integration Tool.

Handles: Lead/Contact/Opportunity management, Account lookup,
         Case creation, and custom object queries.

Production: Calls Salesforce REST API with OAuth2 bearer token.
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


class SalesforceTool(EnterpriseTool):
    name = "salesforce_crm"
    description = "Salesforce CRM: leads, contacts, opportunities, accounts, cases"

    def __init__(
        self,
        instance_url: str,
        access_token: str = "",
        env: str = "production",
    ):
        super().__init__(env=env)
        self.instance_url = instance_url.rstrip("/")
        self.access_token = access_token
        self.api_version = "v59.0"
        self.http = httpx.AsyncClient(
            base_url=f"{self.instance_url}/services/data/{self.api_version}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        action = params.get("action")

        if action == "create_contact":
            return await self._create_record("Contact", params.get("data", {}))
        elif action == "create_lead":
            return await self._create_record("Lead", params.get("data", {}))
        elif action == "create_opportunity":
            return await self._create_record("Opportunity", params.get("data", {}))
        elif action == "create_case":
            return await self._create_record("Case", params.get("data", {}))
        elif action == "query":
            return await self._query(params.get("soql", ""))
        elif action == "get_record":
            return await self._get_record(params["object"], params["record_id"])
        elif action == "update_record":
            return await self._update_record(
                params["object"], params["record_id"], params.get("data", {})
            )
        else:
            raise ValueError(f"Unknown Salesforce action: {action}")

    async def _create_record(self, sobject: str, data: dict) -> dict:
        resp = await self.http.post(f"/sobjects/{sobject}/", json=data)
        resp.raise_for_status()
        result = resp.json()
        return {"status": "created", "id": result["id"], "object": sobject}

    async def _get_record(self, sobject: str, record_id: str) -> dict:
        resp = await self.http.get(f"/sobjects/{sobject}/{record_id}")
        resp.raise_for_status()
        return {"status": "found", "data": resp.json()}

    async def _update_record(self, sobject: str, record_id: str, data: dict) -> dict:
        resp = await self.http.patch(f"/sobjects/{sobject}/{record_id}", json=data)
        resp.raise_for_status()
        return {"status": "updated", "object": sobject, "id": record_id}

    async def _query(self, soql: str) -> dict:
        resp = await self.http.get("/query/", params={"q": soql})
        resp.raise_for_status()
        data = resp.json()
        return {
            "status": "success",
            "total_size": data.get("totalSize", 0),
            "records": data.get("records", []),
        }

    async def _mock_execute(self, params: dict[str, Any]) -> dict[str, Any]:
        action = params.get("action", "unknown")
        mock_id = f"00Q{uuid.uuid4().hex[:15].upper()}"

        mocks = {
            "create_contact": {
                "status": "created", "id": mock_id, "object": "Contact",
            },
            "create_lead": {
                "status": "created", "id": mock_id, "object": "Lead",
            },
            "create_opportunity": {
                "status": "created", "id": mock_id, "object": "Opportunity",
                "data": {"Amount": params.get("data", {}).get("Amount", 0)},
            },
            "create_case": {
                "status": "created", "id": mock_id, "object": "Case",
                "data": {"CaseNumber": f"CASE-{uuid.uuid4().hex[:6].upper()}"},
            },
            "query": {
                "status": "success", "total_size": 0, "records": [],
            },
            "get_record": {
                "status": "found",
                "data": {"Id": params.get("record_id", mock_id), "Name": "Mock Record"},
            },
            "update_record": {
                "status": "updated",
                "object": params.get("object", ""),
                "id": params.get("record_id", mock_id),
            },
        }

        return mocks.get(action, {"status": "mock_success", "action": action})

    async def health_check(self) -> bool:
        if self.mock_mode:
            return True
        try:
            resp = await self.http.get("/sobjects/")
            return resp.status_code < 500
        except Exception:
            return False

    async def close(self):
        await self.http.aclose()
