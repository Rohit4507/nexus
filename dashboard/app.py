"""NEXUS Enterprise Dashboard — Streamlit UI for workflow monitoring.

Features:
- KPI cards (active, completed, breaches, avg response, pending human)
- Workflow status trend charts
- SLA compliance by tier
- Recent workflows table with SLA progress
- Active escalations panel
- Workflow detail drill-down
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import httpx

# ── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="NEXUS Dashboard",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Constants ────────────────────────────────────────────────────────────────
API_BASE_URL = "http://localhost:8000"
REFRESH_INTERVAL = 30  # seconds

# ── Helper Functions ────────────────────────────────────────────────────────


@st.cache_data(ttl=REFRESH_INTERVAL)
def fetch_workflows(status: str | None = None, limit: int = 100) -> list[dict]:
    """Fetch workflows from API with optional status filter."""
    try:
        with httpx.Client(timeout=10) as client:
            params = {"limit": limit}
            if status:
                params["status"] = status
            resp = client.get(f"{API_BASE_URL}/workflows/", params=params)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        st.error(f"Failed to fetch workflows: {e}")
        return []


@st.cache_data(ttl=REFRESH_INTERVAL)
def fetch_health() -> dict:
    """Fetch system health status."""
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(f"{API_BASE_URL}/health")
            resp.raise_for_status()
            return resp.json()
    except Exception:
        return {"status": "unhealthy", "version": "unknown"}


@st.cache_data(ttl=REFRESH_INTERVAL)
def fetch_tools_health() -> dict:
    """Fetch tool integration health."""
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(f"{API_BASE_URL}/health/tools")
            resp.raise_for_status()
            return resp.json()
    except Exception:
        return {"status": "unknown", "tools": {}}


def calculate_metrics(workflows: list[dict]) -> dict[str, Any]:
    """Calculate KPI metrics from workflow list."""
    if not workflows:
        return {
            "active": 0,
            "completed_today": 0,
            "breaches": 0,
            "avg_response_hours": 0,
            "pending_human": 0,
        }

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    active = sum(1 for w in workflows if w.get("status") in ("pending", "in_progress"))
    completed_today = sum(
        1 for w in workflows
        if w.get("status") == "completed" and w.get("completed_at")
        and datetime.fromisoformat(w["completed_at"].replace("Z", "+00:00")) >= today_start
    )

    # Estimate breaches (workflows running > 24 hours)
    breaches = 0
    for w in workflows:
        if w.get("status") in ("pending", "in_progress"):
            created = w.get("created_at")
            if created:
                try:
                    created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    if (now - created_dt).total_seconds() > 86400:
                        breaches += 1
                except Exception:
                    pass

    # Pending human (escalated workflows)
    pending_human = sum(1 for w in workflows if w.get("status") == "escalated")

    # Average response time (completed workflows)
    completed = [w for w in workflows if w.get("status") == "completed" and w.get("completed_at")]
    avg_response = 0
    if completed:
        total_hours = 0
        count = 0
        for w in completed:
            try:
                created = datetime.fromisoformat(w["created_at"].replace("Z", "+00:00"))
                completed_at = datetime.fromisoformat(w["completed_at"].replace("Z", "+00:00"))
                hours = (completed_at - created).total_seconds() / 3600
                total_hours += hours
                count += 1
            except Exception:
                pass
        avg_response = round(total_hours / count, 2) if count > 0 else 0

    return {
        "active": active,
        "completed_today": completed_today,
        "breaches": breaches,
        "avg_response_hours": avg_response,
        "pending_human": pending_human,
    }


def create_status_trend_chart(workflows: list[dict]) -> go.Figure:
    """Create 7-day workflow status trend."""
    if not workflows:
        return go.Figure().add_annotation(text="No data", xref="paper", yref="paper")

    # Group by date and status
    date_status: dict[str, dict[str, int]] = {}
    for w in workflows:
        try:
            created = w.get("created_at", "")
            if created:
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                date_str = dt.strftime("%Y-%m-%d")
                status = w.get("status", "unknown")
                if date_str not in date_status:
                    date_status[date_str] = {}
                date_status[date_str][status] = date_status[date_str].get(status, 0) + 1
        except Exception:
            pass

    if not date_status:
        return go.Figure().add_annotation(text="No data", xref="paper", yref="paper")

    # Convert to DataFrame
    rows = []
    for date, statuses in sorted(date_status.items()):
        for status, count in statuses.items():
            rows.append({"date": date, "status": status, "count": count})

    df = pd.DataFrame(rows)

    fig = px.line(
        df,
        x="date",
        y="count",
        color="status",
        markers=True,
        title="Workflow Status Trend (7 Days)",
        color_discrete_map={
            "pending": "#FFA500",
            "in_progress": "#2196F3",
            "completed": "#4CAF50",
            "failed": "#F44336",
            "escalated": "#9C27B0",
        },
    )
    fig.update_layout(xaxis_title="Date", yaxis_title="Workflows", hovermode="x unified")
    return fig


def create_sla_compliance_chart(workflows: list[dict]) -> go.Figure:
    """Create SLA compliance gauge by workflow type."""
    if not workflows:
        return go.Figure()

    # Calculate compliance by type
    type_stats: dict[str, dict[str, int]] = {}
    for w in workflows:
        wf_type = w.get("workflow_type", "unknown")
        status = w.get("status", "unknown")
        if wf_type not in type_stats:
            type_stats[wf_type] = {"compliant": 0, "non_compliant": 0}
        if status in ("completed", "in_progress", "pending"):
            type_stats[wf_type]["compliant"] += 1
        else:
            type_stats[wf_type]["non_compliant"] += 1

    # Create gauge charts
    fig = go.Figure()

    types = list(type_stats.keys())[:4]  # Limit to 4 types
    compliance_rates = []

    for t in types:
        total = type_stats[t]["compliant"] + type_stats[t]["non_compliant"]
        rate = (type_stats[t]["compliant"] / total * 100) if total > 0 else 100
        compliance_rates.append(rate)

    df = pd.DataFrame({
        "Type": types,
        "Compliance Rate": compliance_rates,
    })

    fig = px.bar(
        df,
        x="Type",
        y="Compliance Rate",
        title="SLA Compliance by Workflow Type",
        color="Compliance Rate",
        color_continuous_scale=["#F44336", "#FFA500", "#4CAF50"],
        range_y=[0, 100],
    )
    fig.update_layout(yaxis_title="Compliance %", showlegend=False)
    return fig


def trigger_workflow(workflow_type: str, payload: dict) -> dict:
    """Trigger a new workflow via API."""
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                f"{API_BASE_URL}/workflows/trigger",
                json={"workflow_type": workflow_type, "payload": payload},
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Failed: {e}"}


# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("🤖 NEXUS")
    st.caption("Enterprise Agentic AI Platform")

    st.divider()

    # Health status
    health = fetch_health()
    status_color = "🟢" if health.get("status") == "healthy" else "🔴"
    st.markdown(f"**Status:** {status_color} {health.get('status', 'unknown')}")
    st.markdown(f"**Version:** {health.get('version', 'unknown')}")

    st.divider()

    # Filters
    st.subheader("Filters")
    status_filter = st.selectbox(
        "Status",
        ["All", "pending", "in_progress", "completed", "failed", "escalated"],
    )
    type_filter = st.selectbox(
        "Workflow Type",
        ["All", "procurement", "onboarding", "contract", "meeting"],
    )

    st.divider()

    # Quick trigger
    st.subheader("Quick Trigger")
    trigger_type = st.selectbox(
        "Type",
        ["procurement", "onboarding", "contract", "meeting"],
    )

    if trigger_type == "procurement":
        item = st.text_input("Item", "Dell Monitor")
        quantity = st.number_input("Quantity", min_value=1, value=5)
        unit_price = st.number_input("Unit Price ($)", min_value=0.0, value=300.0)
        payload = {"item": item, "quantity": quantity, "unit_price": unit_price}
    elif trigger_type == "onboarding":
        name = st.text_input("Employee Name", "John Smith")
        role = st.text_input("Role", "Software Engineer")
        dept = st.selectbox("Department", ["engineering", "sales", "hr", "finance"])
        payload = {"employee_name": name, "role": role, "department": dept}
    elif trigger_type == "contract":
        party = st.text_input("Counterparty", "Acme Corp")
        contract_type = st.selectbox("Type", ["NDA", "MSA", "SOW", "Amendment"])
        amount = st.number_input("Amount ($)", min_value=0.0, value=50000.0)
        payload = {"party_b": party, "contract_type": contract_type, "amount": amount}
    else:
        title = st.text_input("Meeting Title", "Sprint Planning")
        payload = {"title": title}

    if st.button("🚀 Trigger Workflow", use_container_width=True):
        with st.spinner("Triggering workflow..."):
            result = trigger_workflow(trigger_type, payload)
            if "error" in result:
                st.error(result["error"])
            else:
                st.success(f"Workflow {result.get('workflow_id', '')[:8]}... triggered!")

    st.divider()

    # Tool health
    tools_health = fetch_tools_health()
    st.subheader("Tool Health")
    for tool_name, tool_status in tools_health.get("tools", {}).items():
        icon = "✅" if tool_status.get("healthy") else "❌"
        mock = " (mock)" if tool_status.get("mock_mode") else ""
        st.markdown(f"{icon} {tool_name}{mock}")

# ── Main Content ─────────────────────────────────────────────────────────────

st.title("📊 NEXUS Enterprise Dashboard")

# Auto-refresh
if st.checkbox("Auto-refresh", value=True):
    st.autorun = True

# Fetch data
status_param = None if status_filter == "All" else status_filter
workflows = fetch_workflows(status=status_param, limit=200)
metrics = calculate_metrics(workflows)

# KPI Cards
col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    st.metric(
        label="Active Workflows",
        value=metrics["active"],
        delta=None,
    )

with col2:
    st.metric(
        label="Completed Today",
        value=metrics["completed_today"],
        delta=None,
    )

with col3:
    st.metric(
        label="SLA Breaches",
        value=metrics["breaches"],
        delta=-metrics["breaches"],
        delta_color="inverse",
    )

with col4:
    st.metric(
        label="Avg Response Time",
        value=f"{metrics['avg_response_hours']}h",
        delta=None,
    )

with col5:
    st.metric(
        label="Pending Human Review",
        value=metrics["pending_human"],
        delta=None,
    )

st.divider()

# Charts
col1, col2 = st.columns(2)

with col1:
    st.subheader("Workflow Status Trend")
    trend_fig = create_status_trend_chart(workflows)
    st.plotly_chart(trend_fig, use_container_width=True)

with col2:
    st.subheader("SLA Compliance by Type")
    sla_fig = create_sla_compliance_chart(workflows)
    st.plotly_chart(sla_fig, use_container_width=True)

st.divider()

# Recent Workflows and Escalations
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("Recent Workflows")

    if workflows:
        # Prepare data for table
        df_workflows = pd.DataFrame(workflows)

        # Format timestamps
        df_workflows["created_at"] = pd.to_datetime(df_workflows["created_at"]).dt.strftime(
            "%Y-%m-%d %H:%M"
        )
        if "completed_at" in df_workflows.columns:
            df_workflows["completed_at"] = pd.to_datetime(
                df_workflows["completed_at"], errors="coerce"
            ).dt.strftime("%Y-%m-%d %H:%M")

        # Calculate SLA progress (mock calculation based on time elapsed)
        def calc_sla_progress(row):
            try:
                created = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                elapsed = (now - created).total_seconds()
                # Assume 24h SLA for demo
                return min(100, int(elapsed / 86400 * 100))
            except Exception:
                return 0

        df_workflows["sla_progress"] = df_workflows.apply(calc_sla_progress, axis=1)

        # Display table with styling
        st.dataframe(
            df_workflows[
                ["workflow_id", "workflow_type", "status", "sla_progress", "created_at"]
            ].head(20),
            column_config={
                "workflow_id": st.column_config.TextColumn("ID", width="medium"),
                "workflow_type": st.column_config.TextColumn("Type", width="small"),
                "status": st.column_config.TextColumn("Status", width="small"),
                "sla_progress": st.column_config.ProgressColumn(
                    "SLA Progress", min=0, max=100, format="%d%%"
                ),
                "created_at": st.column_config.TextColumn("Created", width="medium"),
            },
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info("No workflows found. Trigger one from the sidebar!")

with col2:
    st.subheader("🔴 Active Escalations")

    escalated = [w for w in workflows if w.get("status") == "escalated"]

    if escalated:
        for esc in escalated[:5]:  # Show top 5
            wf_id = esc.get("workflow_id", "")[:8]
            wf_type = esc.get("workflow_type", "unknown")
            created = esc.get("created_at", "")

            # Calculate wait time
            wait_time = "Unknown"
            if created:
                try:
                    created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    elapsed = datetime.now(timezone.utc) - created_dt
                    hours = elapsed.total_seconds() / 3600
                    wait_time = f"{hours:.1f}h"
                except Exception:
                    pass

            with st.expander(f"{wf_type.upper()}: {wf_id}..."):
                st.markdown(f"**Wait Time:** {wait_time}")
                st.markdown(f"**Created:** {created}")
                if st.button("Review", key=f"review_{wf_id}"):
                    st.session_state["reviewing"] = esc.get("workflow_id")
    else:
        st.success("No active escalations!")

st.divider()

# Workflow Detail Drill-down
st.subheader("Workflow Detail Drill-down")

workflow_ids = [w.get("workflow_id", "") for w in workflows]
selected_id = st.selectbox("Select Workflow ID", options=workflow_ids)

if selected_id:
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(f"{API_BASE_URL}/workflows/{selected_id}")
            if resp.status_code == 200:
                wf = resp.json()
                st.json(wf)
            else:
                st.error("Failed to fetch workflow details")
    except Exception as e:
        st.error(f"Error: {e}")

# Footer
st.divider()
st.caption(
    f"NEXUS Dashboard v0.1.0 | Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | "
    f"Auto-refresh: {REFRESH_INTERVAL}s"
)
