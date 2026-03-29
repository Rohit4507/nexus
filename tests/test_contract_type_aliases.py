from __future__ import annotations

from nexus.memory.contract_type_aliases import canonical_contract_type
from nexus.memory.vector import normalize_static_metadata, prepare_static_filter, static_metadata_matches


def test_canonical_contract_type_maps_common_aliases() -> None:
    assert canonical_contract_type("Master Services Agreement") == "msa"
    assert canonical_contract_type("Non Disclosure Agreement") == "nda"
    assert canonical_contract_type("Statement of Work") == "sow"
    assert canonical_contract_type("random custom type") == "general"


def test_normalize_static_metadata_applies_defaults_and_aliases() -> None:
    out = normalize_static_metadata({"contract_type": "master service agreement"})
    assert out["contract_type"] == "msa"
    assert out["doc_type"] == "unknown"
    assert out["jurisdiction"] == "US"
    assert out["risk_tag"] == "general"
    assert out["version"] == "1.0"


def test_prepare_filter_and_matching_support_wildcards() -> None:
    stored = normalize_static_metadata(
        {
            "doc_type": "policy_clause",
            "jurisdiction": "US",
            "contract_type": "msa",
            "risk_tag": "general",
            "version": "1.0",
        }
    )
    filt = prepare_static_filter(
        {
            "doc_type": "policy_clause",
            "contract_type": "Master Services Agreement",
            "version": "*",
        }
    )
    assert filt is not None
    assert filt["contract_type"] == "msa"
    assert static_metadata_matches(stored, filt) is True
