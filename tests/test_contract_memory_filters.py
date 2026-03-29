from __future__ import annotations

import pytest

from nexus.agents.execution.contracts import ContractAgent


class _DummyTools:
    pass


class _DummyLLM:
    pass


@pytest.mark.asyncio
async def test_contract_retrieval_uses_five_key_metadata_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class FakeMemory:
        async def search_static(self, query: str, k: int, metadata_filter: dict):
            captured["query"] = query
            captured["k"] = k
            captured["metadata_filter"] = metadata_filter
            return [{"text": "policy-1", "metadata": metadata_filter, "score": 0.1}]

        async def close(self) -> None:
            return None

    import nexus.memory.vector as vector_mod

    monkeypatch.setattr(vector_mod, "VectorMemoryManager", FakeMemory)

    agent = ContractAgent(tool_registry=_DummyTools(), llm_router=_DummyLLM())
    payload = {"jurisdiction": "US", "policy_version": "1.0"}
    terms = {"contract_type": "Master Services Agreement", "party_b": "VendorX"}

    result = await agent._retrieve_policy_context(payload=payload, terms=terms, mode="baseline")

    assert len(result) == 1
    mf = captured["metadata_filter"]
    assert set(mf.keys()) == {
        "doc_type",
        "jurisdiction",
        "contract_type",
        "risk_tag",
        "version",
    }
    assert mf["doc_type"] == "policy_clause"
    assert mf["jurisdiction"] == "US"
    assert mf["contract_type"] == "msa"
    assert mf["risk_tag"] == "general"
    assert mf["version"] == "1.0"


def test_contract_metadata_builder_handles_mitigation_risk() -> None:
    agent = ContractAgent(tool_registry=_DummyTools(), llm_router=_DummyLLM())
    payload = {"jurisdiction": "IN", "policy_version": "2.1"}
    terms = {"contract_type": "NDA"}
    risk = {"risk_level": "HIGH"}

    out = agent._static_policy_metadata(payload, terms, "mitigation", risk)

    assert out == {
        "doc_type": "mitigation_playbook",
        "jurisdiction": "IN",
        "contract_type": "nda",
        "risk_tag": "high",
        "version": "2.1",
    }
