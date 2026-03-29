from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from nexus.agents import sla_monitor


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.updated_ids = []
        self.committed = False

    async def execute(self, _query, params=None):
        if params and "id" in params:
            self.updated_ids.append(str(params["id"]))
            return _FakeResult([])
        return _FakeResult(self.rows)

    async def commit(self):
        self.committed = True


class _FakeSessionCtx:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_check_all_active_workflows_escalates_breaches(monkeypatch: pytest.MonkeyPatch):
    now = datetime.now(timezone.utc)
    rows = [
        {"id": "wf-warning", "workflow_type": "contract", "created_at": now - timedelta(days=6), "status": "in_progress"},
        {"id": "wf-breach", "workflow_type": "procurement", "created_at": now - timedelta(hours=2), "status": "pending"},
        {"id": "wf-ok", "workflow_type": "meeting", "created_at": now - timedelta(minutes=2), "status": "in_progress"},
    ]
    fake_session = _FakeSession(rows)

    class FakeMonitoringAgent:
        def __init__(self, _session, _audit):
            pass

        async def check_sla(self, workflow_dict):
            wf_id = workflow_dict["workflow_id"]
            if wf_id == "wf-warning":
                return {"status": "warning"}
            if wf_id == "wf-breach":
                return {"status": "breached"}
            return {"status": "ok"}

    monkeypatch.setattr(sla_monitor, "async_session_factory", lambda: _FakeSessionCtx(fake_session))
    monkeypatch.setattr(sla_monitor, "MonitoringAgent", FakeMonitoringAgent)
    monkeypatch.setattr(sla_monitor, "AuditLogger", lambda _session: object())

    await sla_monitor._check_all_active_workflows()

    assert fake_session.committed is True
    assert fake_session.updated_ids == ["wf-breach"]


@pytest.mark.asyncio
async def test_check_all_active_workflows_skips_commit_when_no_rows(monkeypatch: pytest.MonkeyPatch):
    fake_session = _FakeSession([])

    class FakeMonitoringAgent:
        def __init__(self, _session, _audit):
            pass

        async def check_sla(self, workflow_dict):
            return {"status": "ok"}

    monkeypatch.setattr(sla_monitor, "async_session_factory", lambda: _FakeSessionCtx(fake_session))
    monkeypatch.setattr(sla_monitor, "MonitoringAgent", FakeMonitoringAgent)
    monkeypatch.setattr(sla_monitor, "AuditLogger", lambda _session: object())

    await sla_monitor._check_all_active_workflows()

    assert fake_session.committed is False
    assert fake_session.updated_ids == []
