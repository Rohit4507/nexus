"""Bootstrap static (FAISS) chunks with full five-key metadata.

Run:  python -m nexus.memory.ingest_static

Requires Ollama with ``nomic-embed-text`` for embeddings.
"""

from __future__ import annotations

import asyncio

import structlog

from nexus.memory.contract_type_aliases import CONTRACT_TYPE_ALIASES
from nexus.memory.vector import VectorMemoryManager, normalize_static_metadata

logger = structlog.get_logger()

# Sample corpora — ``contract_type`` values must be canonical slugs (values in ``CONTRACT_TYPE_ALIASES``).
SAMPLE_CHUNKS: list[tuple[str, dict]] = [
    (
        "Limitation of liability shall not exceed the fees paid in the twelve months preceding the claim.",
        {
            "doc_type": "policy_clause",
            "jurisdiction": "US",
            "contract_type": "nda",
            "risk_tag": "general",
            "version": "1.0",
        },
    ),
    (
        "Indemnification shall be mutual and proportional to fault; no unlimited indemnity for indirect damages.",
        {
            "doc_type": "policy_clause",
            "jurisdiction": "US",
            "contract_type": "msa",
            "risk_tag": "general",
            "version": "1.0",
        },
    ),
    (
        "Mitigation: cap unlimited liability at contract value; require commercially reasonable insurance.",
        {
            "doc_type": "mitigation_playbook",
            "jurisdiction": "US",
            "contract_type": "msa",
            "risk_tag": "high",
            "version": "1.0",
        },
    ),
    (
        "Mitigation for medium risk: add 30-day termination for convenience and annual renewal opt-out.",
        {
            "doc_type": "mitigation_playbook",
            "jurisdiction": "US",
            "contract_type": "nda",
            "risk_tag": "medium",
            "version": "1.0",
        },
    ),
]


async def ingest() -> None:
    allowed = set(CONTRACT_TYPE_ALIASES.values())
    for _, meta in SAMPLE_CHUNKS:
        ct = meta.get("contract_type", "")
        if ct not in allowed:
            raise ValueError(f"ingest_static: contract_type {ct!r} is not a canonical slug")
    texts = [t for t, _ in SAMPLE_CHUNKS]
    metas = [normalize_static_metadata(m) for _, m in SAMPLE_CHUNKS]
    mgr = VectorMemoryManager()
    try:
        await mgr.upsert_static(texts=texts, metadatas=metas)
        logger.info("ingest_static_complete", chunks=len(texts))
    finally:
        await mgr.close()


def main() -> None:
    asyncio.run(ingest())


if __name__ == "__main__":
    main()
