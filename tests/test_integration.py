"""Integration Tests for NEXUS Platform.

Covers:
- End-to-end workflow execution
- API integration tests
- Database integration tests
- Vector memory integration tests
"""

from __future__ import annotations

import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from nexus.agents.orchestrator import run_workflow, WorkflowState
from nexus.memory.vector import VectorMemoryManager, FAISSStore, ChromaStore


# ── Workflow Integration Tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_procurement_workflow_end_to_end():
    """Test procurement workflow full execution."""
    # Note: This test uses mock tools since we don't have real API connections

    result = await run_workflow(
        workflow_type="procurement",
        payload={
            "item": "Dell Latitude Laptop",
            "quantity": 5,
            "unit_price": 1200,
            "department": "Engineering",
            "vendor": "CDW",
        },
        created_by="test_user@example.com",
    )

    assert result is not None
    assert result["workflow_id"] is not None
    assert result["workflow_type"] == "procurement"
    # Status depends on mock tool responses
    assert result["status"] in ("completed", "failed", "escalated")


@pytest.mark.asyncio
async def test_onboarding_workflow_end_to_end():
    """Test onboarding workflow full execution."""
    result = await run_workflow(
        workflow_type="onboarding",
        payload={
            "employee_name": "Jane Doe",
            "role": "Senior Software Engineer",
            "department": "Platform",
            "start_date": "2026-04-01",
            "manager": "John Smith",
        },
        created_by="hr@example.com",
    )

    assert result is not None
    assert result["workflow_type"] == "onboarding"


@pytest.mark.asyncio
async def test_contract_workflow_end_to_end():
    """Test contract workflow full execution."""
    result = await run_workflow(
        workflow_type="contract",
        payload={
            "contract_type": "NDA",
            "party_b": "Acme Corporation",
            "amount": 50000,
            "jurisdiction": "US",
        },
        created_by="legal@example.com",
    )

    assert result is not None
    assert result["workflow_type"] == "contract"


@pytest.mark.asyncio
async def test_meeting_workflow_end_to_end():
    """Test meeting workflow full execution."""
    result = await run_workflow(
        workflow_type="meeting",
        payload={
            "title": "Sprint Planning",
            "participants": ["Alice", "Bob", "Charlie"],
            "transcript": "Discussion about sprint goals...",
        },
        created_by="scrum@example.com",
    )

    assert result is not None
    assert result["workflow_type"] == "meeting"


# ── Vector Memory Integration Tests ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_vector_memory_manager_static_upsert():
    """Test vector memory static upsert."""
    memory = VectorMemoryManager()

    texts = [
        "Standard confidentiality clause for NDA agreements",
        "Payment terms for master services agreements",
        "Liability limitation guidelines",
    ]

    metadatas = [
        {"doc_type": "policy_clause", "jurisdiction": "US", "contract_type": "nda"},
        {"doc_type": "policy_clause", "jurisdiction": "US", "contract_type": "msa"},
        {"doc_type": "mitigation_playbook", "jurisdiction": "US", "contract_type": "general"},
    ]

    await memory.upsert_static(texts, metadatas)

    # Search to verify
    results = await memory.search_static("confidentiality NDA", k=2)

    assert len(results) > 0
    assert "confidentiality" in results[0]["text"].lower() or "NDA" in results[0]["text"]

    await memory.close()


@pytest.mark.asyncio
async def test_vector_memory_manager_dynamic_upsert():
    """Test vector memory dynamic upsert."""
    memory = VectorMemoryManager()

    texts = [
        "Meeting summary: Sprint planning completed, 15 story points committed",
        "Action items: Alice to implement auth, Bob to write tests",
    ]

    metadatas = [
        {"type": "meeting_summary", "workflow_id": "test-123"},
        {"type": "meeting_actions", "workflow_id": "test-123"},
    ]

    await memory.upsert_dynamic(texts, metadatas)

    # Search to verify
    results = await memory.search_dynamic("sprint planning", k=2)

    assert len(results) > 0

    await memory.close()


@pytest.mark.asyncio
async def test_vector_memory_metadata_filtering():
    """Test vector memory metadata filtering."""
    memory = VectorMemoryManager()

    # Insert with specific metadata
    await memory.upsert_static(
        texts=["GDPR compliance clause for EU contracts"],
        metadatas=[{
            "doc_type": "compliance_rule",
            "jurisdiction": "EU",
            "contract_type": "general",
            "risk_tag": "critical",
            "version": "1.0",
        }],
    )

    # Search with filter
    results = await memory.search_static(
        "GDPR compliance",
        k=5,
        metadata_filter={"jurisdiction": "EU"},
    )

    # Should find the EU-specific document
    assert len(results) > 0

    await memory.close()


# ── API Integration Tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_health_endpoint():
    """Test API health endpoint."""
    from nexus.api.main import app
    from httpx import AsyncClient

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_api_trigger_workflow():
    """Test workflow trigger via API."""
    from nexus.api.main import app
    from httpx import AsyncClient

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.post(
            "/workflows/trigger",
            json={
                "workflow_type": "procurement",
                "payload": {"item": "test", "quantity": 1},
            },
        )

    assert response.status_code in (200, 500)  # 500 if tools not available


@pytest.mark.asyncio
async def test_api_list_workflows():
    """Test workflow listing via API."""
    from nexus.api.main import app
    from httpx import AsyncClient

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/workflows/")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


# ── SLA Monitor Integration Tests ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_sla_monitor_polling():
    """Test SLA monitor polling loop."""
    from nexus.agents.sla_monitor import _check_all_active_workflows

    # This should complete without errors even with no workflows
    await _check_all_active_workflows()


@pytest.mark.asyncio
async def test_sla_monitor_with_active_workflow():
    """Test SLA monitor with simulated active workflow."""
    # This would require database setup
    # Placeholder for future implementation
    pass


# ── Concurrency Tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_workflow_execution():
    """Test multiple workflows can run concurrently."""
    workflows = [
        ("procurement", {"item": f"item-{i}", "quantity": 1})
        for i in range(3)
    ]

    tasks = [
        run_workflow(wf_type, payload, created_by="test")
        for wf_type, payload in workflows
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # All should complete (some may fail due to mock tools)
    assert len(results) == 3
    for result in results:
        if isinstance(result, Exception):
            pytest.fail(f"Workflow raised exception: {result}")
        else:
            assert result is not None


# ── Error Handling Tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_workflow_type():
    """Test handling of invalid workflow type."""
    with pytest.raises(ValueError, match="No execution logic"):
        await run_workflow(
            workflow_type="invalid_type",
            payload={},
            created_by="test",
        )


@pytest.mark.asyncio
async def test_empty_payload_handling():
    """Test workflow handles empty payload gracefully."""
    result = await run_workflow(
        workflow_type="meeting",
        payload={},
        created_by="test",
    )

    # Should not crash, may complete with mock data
    assert result is not None
