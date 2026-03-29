"""Mandatory contract-type normalization for FAISS metadata and retrieval.

Every extracted or payload ``contract_type`` string is mapped to a **canonical slug**
via ``CONTRACT_TYPE_ALIASES``. Unknown inputs resolve to ``general``.
"""

from __future__ import annotations

# Keys: lowercase, normalized spacing. Values: canonical slug (stable for indexes).
CONTRACT_TYPE_ALIASES: dict[str, str] = {
    # Canonical slugs (identity)
    "general": "general",
    "nda": "nda",
    "msa": "msa",
    "sow": "sow",
    "dpa": "dpa",
    "order_form": "order_form",
    "license": "license",
    "amendment": "amendment",
    "psa": "psa",
    "rfp": "rfp",
    "rfq": "rfq",
    # NDA family
    "non-disclosure agreement": "nda",
    "non disclosure agreement": "nda",
    "confidentiality agreement": "nda",
    "mutual nda": "nda",
    "mutual non-disclosure agreement": "nda",
    "one-way nda": "nda",
    "secrecy agreement": "nda",
    # MSA / services
    "master services agreement": "msa",
    "master service agreement": "msa",
    "services agreement": "msa",
    "framework agreement": "msa",
    "umbrella agreement": "msa",
    "consulting agreement": "msa",
    "professional services agreement": "msa",
    # SOW
    "statement of work": "sow",
    "work order": "sow",
    "schedule": "sow",
    # DPA
    "data processing agreement": "dpa",
    "data processing addendum": "dpa",
    "data protection agreement": "dpa",
    "dpa": "dpa",
    # Orders
    "order form": "order_form",
    "purchase order": "order_form",
    "p.o.": "order_form",
    "po": "order_form",
    # License
    "software license agreement": "license",
    "software license": "license",
    "eula": "license",
    "end user license agreement": "license",
    "subscription agreement": "license",
    # Amendment
    "contract amendment": "amendment",
    "addendum": "amendment",
    # Other
    "partner agreement": "psa",
    "partnering agreement": "psa",
    "request for proposal": "rfp",
    "request for quotation": "rfq",
}


def canonical_contract_type(raw: str | None) -> str:
    """Map free-text contract type to a canonical slug for FAISS filters."""
    if raw is None:
        return "general"
    s = " ".join(str(raw).strip().lower().split())
    if not s:
        return "general"
    if s in CONTRACT_TYPE_ALIASES:
        return CONTRACT_TYPE_ALIASES[s]
    for key in sorted(CONTRACT_TYPE_ALIASES.keys(), key=len, reverse=True):
        if len(key) <= 3:
            if s == key:
                return CONTRACT_TYPE_ALIASES[key]
        elif key in s:
            return CONTRACT_TYPE_ALIASES[key]
    return "general"
