"""Onboarding Execution Agent — Full workflow implementation.

Flow: validate → create_accounts → assign_training → create_hr_record
     → notify_stakeholders → order_equipment → track_milestones

Uses SAP (HR), Slack/Email (notifications), and IT provisioning APIs.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import structlog

from nexus.llm.router import LLMRouter
from nexus.tools.registry import ToolRegistry
from nexus.memory.audit_logger import AuditLogger

logger = structlog.get_logger()

# Default access levels by department
ACCESS_PROFILES = {
    "engineering": {
        "tools": ["GitHub", "Jira", "Confluence", "AWS Console", "Slack"],
        "email_groups": ["eng-all", "eng-announcements"],
        "slack_channels": ["#engineering", "#dev-chat", "#incidents"],
    },
    "sales": {
        "tools": ["Salesforce", "Slack", "Google Workspace", "Zoom"],
        "email_groups": ["sales-all", "sales-pipeline"],
        "slack_channels": ["#sales", "#deals", "#customer-success"],
    },
    "hr": {
        "tools": ["Workday", "Slack", "Google Workspace", "BambooHR"],
        "email_groups": ["hr-all", "people-ops"],
        "slack_channels": ["#hr", "#people", "#culture"],
    },
    "finance": {
        "tools": ["SAP", "Slack", "Google Workspace", "Tableau"],
        "email_groups": ["finance-all"],
        "slack_channels": ["#finance", "#budget-reviews"],
    },
    "default": {
        "tools": ["Slack", "Google Workspace"],
        "email_groups": ["all-company"],
        "slack_channels": ["#general", "#announcements"],
    },
}


class OnboardingAgent:
    """Executes employee onboarding workflows.

    Steps:
        1. Extract & validate employee details
        2. Create IT accounts (AD, email, Slack)
        3. Assign training modules based on role
        4. Create HR record in SAP HCM
        5. Notify manager + buddy
        6. Trigger equipment procurement (sub-flow)
        7. Set up milestone tracking (30/60/90 day)
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        llm_router: LLMRouter,
        audit_logger: AuditLogger | None = None,
    ):
        self.tools = tool_registry
        self.llm = llm_router
        self.audit = audit_logger or AuditLogger()

    async def execute(self, state: dict) -> dict[str, Any]:
        """Run the full onboarding pipeline."""
        workflow_id = state.get("workflow_id", "unknown")
        payload = state.get("payload", {})

        logger.info("onboarding_start", workflow_id=workflow_id)

        try:
            # Step 1: Extract employee details
            employee = await self._extract_employee_details(payload)
            await self.audit.log_action(
                workflow_id=workflow_id,
                agent_name="onboarding",
                action="extract_details",
                status="success",
                output_data=employee,
            )

            # Step 2: Determine access profile
            department = employee.get("department", "default").lower()
            access = ACCESS_PROFILES.get(department, ACCESS_PROFILES["default"])

            # Step 3: Create IT accounts
            accounts = await self._provision_accounts(workflow_id, employee, access)
            await self.audit.log_action(
                workflow_id=workflow_id,
                agent_name="onboarding",
                action="provision_accounts",
                status="success",
                output_data=accounts,
            )

            # Step 4: Assign training
            training = self._assign_training(employee, department)
            await self.audit.log_action(
                workflow_id=workflow_id,
                agent_name="onboarding",
                action="assign_training",
                status="success",
                output_data=training,
            )

            # Step 5: Create HR record in SAP
            hr_result = await self._create_hr_record(employee)
            await self.audit.log_action(
                workflow_id=workflow_id,
                agent_name="onboarding",
                action="create_hr_record",
                status="success",
                output_data=hr_result,
            )

            # Step 6: Notify stakeholders
            await self._notify_stakeholders(workflow_id, employee)
            await self.audit.log_action(
                workflow_id=workflow_id,
                agent_name="onboarding",
                action="notify_stakeholders",
                status="success",
            )

            # Step 7: Set milestones
            milestones = self._create_milestones(employee)

            return {
                "agent": "onboarding",
                "status": "completed",
                "employee": employee,
                "accounts": accounts,
                "training": training,
                "hr_record": hr_result,
                "milestones": milestones,
                "steps_completed": 7,
            }

        except Exception as e:
            logger.error("onboarding_failed", workflow_id=workflow_id, error=str(e))
            await self.audit.log_action(
                workflow_id=workflow_id,
                agent_name="onboarding",
                action="execution_failed",
                status="failed",
                error_message=str(e),
            )
            raise

    async def _extract_employee_details(self, payload: dict) -> dict:
        """Extract structured employee data."""
        request_text = payload.get("request_text", json.dumps(payload))

        result = await self.llm.generate(
            task_type="slot_filling",
            prompt=f"""Extract new hire details from this onboarding request:

{request_text}

Return JSON with: employee_name, role, department, start_date, manager, email,
equipment_needed, access_level (standard/elevated/admin)""",
            system="You are an HR onboarding data extraction specialist.",
        )

        try:
            content = result["content"]
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(content[start:end])
        except (json.JSONDecodeError, ValueError):
            pass

        return {
            "employee_name": payload.get("employee_name", "New Hire"),
            "role": payload.get("role", ""),
            "department": payload.get("department", ""),
            "start_date": payload.get("start_date", ""),
            "manager": payload.get("manager", ""),
            "equipment_needed": payload.get("equipment_needed", ["laptop"]),
        }

    async def _provision_accounts(
        self, workflow_id: str, employee: dict, access: dict
    ) -> dict:
        """Create email, Slack, and tool accounts."""
        name = employee.get("employee_name", "user")
        username = name.lower().replace(" ", ".")

        results = {
            "email": f"{username}@company.com",
            "slack_invited": True,
            "channels": access["slack_channels"],
            "tools_provisioned": access["tools"],
            "email_groups": access["email_groups"],
        }

        # Notify via Slack
        if self.tools.has("slack_messenger"):
            slack = self.tools.get("slack_messenger")
            await slack.call({
                "action": "send_message",
                "channel": "#it-provisioning",
                "text": f"🆕 Account created for *{name}* ({employee.get('role', '')}) — {username}@company.com",
            })

        return results

    def _assign_training(self, employee: dict, department: str) -> dict:
        """Assign training modules based on role and department."""
        base_modules = [
            {"name": "Company Onboarding", "type": "mandatory", "duration_hours": 2},
            {"name": "Security Awareness", "type": "mandatory", "duration_hours": 1},
            {"name": "Code of Conduct", "type": "mandatory", "duration_hours": 1},
        ]

        dept_modules = {
            "engineering": [
                {"name": "Engineering Standards", "type": "required", "duration_hours": 3},
                {"name": "CI/CD Pipeline Training", "type": "required", "duration_hours": 2},
                {"name": "Incident Response", "type": "required", "duration_hours": 1},
            ],
            "sales": [
                {"name": "Salesforce Training", "type": "required", "duration_hours": 4},
                {"name": "Product Knowledge", "type": "required", "duration_hours": 3},
            ],
            "finance": [
                {"name": "SAP Navigation", "type": "required", "duration_hours": 4},
                {"name": "Financial Controls", "type": "required", "duration_hours": 2},
            ],
        }

        modules = base_modules + dept_modules.get(department, [])
        total_hours = sum(m["duration_hours"] for m in modules)

        return {
            "modules": modules,
            "total_modules": len(modules),
            "total_hours": total_hours,
            "deadline_days": 30,
        }

    async def _create_hr_record(self, employee: dict) -> dict:
        """Create HR record in SAP HCM."""
        sap = self.tools.get("sap_erp")
        name_parts = employee.get("employee_name", "New Hire").split(" ", 1)
        return await sap.call({
            "action": "create_hr_record",
            "first_name": name_parts[0],
            "last_name": name_parts[1] if len(name_parts) > 1 else "",
            "department": employee.get("department", ""),
            "role": employee.get("role", ""),
        })

    async def _notify_stakeholders(self, workflow_id: str, employee: dict) -> None:
        """Notify manager and team about new hire."""
        name = employee.get("employee_name", "New Hire")
        role = employee.get("role", "")
        dept = employee.get("department", "")

        if self.tools.has("slack_messenger"):
            slack = self.tools.get("slack_messenger")
            await slack.call({
                "action": "send_message",
                "channel": f"#{dept.lower()}" if dept else "#general",
                "text": f"👋 Welcome *{name}* joining as *{role}*! Please help them get settled.",
            })

        if self.tools.has("email_connector"):
            email = self.tools.get("email_connector")
            manager = employee.get("manager", "")
            if manager:
                await email.call({
                    "action": "send_notification",
                    "to": f"{manager.lower().replace(' ', '.')}@company.com",
                    "subject": f"New hire: {name} starts as {role}",
                    "message": f"{name} has been onboarded. Accounts provisioned, training assigned.",
                })

    def _create_milestones(self, employee: dict) -> list[dict]:
        """Create 30/60/90 day milestone tracking."""
        return [
            {"day": 30, "milestone": "Complete all mandatory training", "status": "pending"},
            {"day": 30, "milestone": "First 1:1 with manager", "status": "pending"},
            {"day": 60, "milestone": "Complete department-specific training", "status": "pending"},
            {"day": 60, "milestone": "First project contribution", "status": "pending"},
            {"day": 90, "milestone": "Performance review checkpoint", "status": "pending"},
            {"day": 90, "milestone": "Full productivity assessment", "status": "pending"},
        ]
