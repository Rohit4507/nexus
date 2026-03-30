#!/usr/bin/env python3
"""Vector Memory Bootstrap Script — Ingest static policy documents into FAISS.

Usage:
    python -m scripts.bootstrap_vector_memory

This script:
1. Reads policy documents from data/policies/ directory
2. Chunks documents into manageable pieces
3. Extracts metadata (doc_type, jurisdiction, contract_type, risk_tag, version)
4. Upserts into FAISS vector store

Supported document types:
- policy_clause: Standard company policies
- mitigation_playbook: Risk mitigation clauses
- contract_template: Template contracts (NDA, MSA, SOW)
- compliance_rule: Regulatory compliance requirements
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import structlog

from nexus.memory.vector import VectorMemoryManager, normalize_static_metadata
from nexus.memory.contract_type_aliases import canonical_contract_type

logger = structlog.get_logger()

# ── Configuration ────────────────────────────────────────────────────────────

DATA_DIR = Path(__file__).parent.parent / "data" / "policies"
BATCH_SIZE = 10  # Documents per batch


# ── Sample Policy Documents ─────────────────────────────────────────────────
# In production, these would be real documents from legal/compliance teams

SAMPLE_POLICIES = [
    {
        "doc_type": "policy_clause",
        "jurisdiction": "US",
        "contract_type": "nda",
        "risk_tag": "general",
        "version": "1.0",
        "title": "Standard NDA Confidentiality Clause",
        "content": """
        CONFIDENTIALITY OBLIGATIONS
        Each party agrees to maintain the confidentiality of all Confidential
        Information disclosed by the other party. Confidential Information shall
        not be disclosed to third parties without prior written consent, except
        to employees with a legitimate need to know. This obligation shall remain
        in effect for a period of three (3) years from the date of disclosure.
        """,
    },
    {
        "doc_type": "policy_clause",
        "jurisdiction": "US",
        "contract_type": "msa",
        "risk_tag": "general",
        "version": "1.0",
        "title": "Master Services Agreement - Payment Terms",
        "content": """
        PAYMENT TERMS
        Client shall pay all invoices within thirty (30) days of receipt.
        Late payments shall accrue interest at the rate of 1.5% per month
        or the maximum rate permitted by law, whichever is lower. Service
        Provider reserves the right to suspend services for accounts more
        than sixty (60) days past due.
        """,
    },
    {
        "doc_type": "mitigation_playbook",
        "jurisdiction": "US",
        "contract_type": "nda",
        "risk_tag": "high",
        "version": "1.0",
        "title": "High-Risk NDA Mitigation Clauses",
        "content": """
        ENHANCED PROTECTION FOR HIGH-RISK DISCLOSURES
        For disclosures involving trade secrets, source code, or customer data:
        (1) Implement additional access controls and audit logging
        (2) Require recipient to designate specific individuals with access
        (3) Mandate immediate notification of any suspected breach
        (4) Allow disclosing party to request return or destruction of materials
        (5) Include liquidated damages provision for willful misconduct
        """,
    },
    {
        "doc_type": "mitigation_playbook",
        "jurisdiction": "US",
        "contract_type": "msa",
        "risk_tag": "medium",
        "version": "1.0",
        "title": "MSA Liability Cap Guidelines",
        "content": """
        LIABILITY LIMITATION STANDARDS
        For standard-risk MSA agreements:
        (1) Cap liability at 12 months of fees paid under the agreement
        (2) Exclude indirect, consequential, and punitive damages
        (3) Carve out exceptions for: gross negligence, willful misconduct,
            data breaches caused by provider, and IP infringement
        (4) Ensure mutual application of limitations
        """,
    },
    {
        "doc_type": "policy_clause",
        "jurisdiction": "EU",
        "contract_type": "nda",
        "risk_tag": "general",
        "version": "2.0",
        "title": "GDPR-Compliant NDA Data Processing",
        "content": """
        DATA PROTECTION AND GDPR COMPLIANCE
        Where Confidential Information includes personal data of EU residents,
        both parties agree to comply with GDPR requirements. Processing shall
        be limited to the purposes of this agreement. Technical and organizational
        measures shall be implemented to protect personal data. Data subject
        rights shall be respected and facilitated.
        """,
    },
    {
        "doc_type": "contract_template",
        "jurisdiction": "US",
        "contract_type": "nda",
        "risk_tag": "general",
        "version": "1.0",
        "title": "Mutual NDA Template",
        "content": """
        MUTUAL NON-DISCLOSURE AGREEMENT

        This Agreement is entered into by and between the parties identified below.

        1. DEFINITIONS
        "Confidential Information" means any non-public information disclosed by
        one party to the other, whether orally or in writing.

        2. OBLIGATIONS
        Each party agrees to: (a) protect Confidential Information with reasonable
        care; (b) not disclose to third parties without consent; (c) use only for
        the Purpose of evaluating the Business Relationship.

        3. TERM
        This Agreement shall commence on the Effective Date and continue for
        three (3) years, unless terminated earlier.

        4. GOVERNING LAW
        This Agreement shall be governed by the laws of [Jurisdiction].
        """,
    },
    {
        "doc_type": "compliance_rule",
        "jurisdiction": "US",
        "contract_type": "general",
        "risk_tag": "critical",
        "version": "1.0",
        "title": "SOX Compliance - Financial Contract Review",
        "content": """
        SARBANES-OXLEY COMPLIANCE REQUIREMENTS
        All contracts with financial implications exceeding $100,000 must:
        (1) Be reviewed by Finance and Legal departments
        (2) Include explicit revenue recognition terms
        (3) Document internal controls over financial reporting
        (4) Retain audit trail for minimum 7 years
        (5) Be disclosed in quarterly SOX certification if material
        """,
    },
    {
        "doc_type": "policy_clause",
        "jurisdiction": "US",
        "contract_type": "sow",
        "risk_tag": "general",
        "version": "1.0",
        "title": "Statement of Work - Deliverable Acceptance",
        "content": """
        DELIVERABLE ACCEPTANCE CRITERIA
        Client shall have ten (10) business days to review each deliverable.
        Acceptance shall be deemed granted if no written rejection is provided
        within this period. Rejections must specify concrete deficiencies.
        Provider shall have reasonable opportunity to cure deficiencies.
        """,
    },
    {
        "doc_type": "mitigation_playbook",
        "jurisdiction": "US",
        "contract_type": "sow",
        "risk_tag": "high",
        "version": "1.0",
        "title": "SOW Scope Creep Mitigation",
        "content": """
        SCOPE CREEP PREVENTION AND RESPONSE
        For high-risk SOW agreements:
        (1) Define explicit acceptance criteria for each deliverable
        (2) Include change order process with pricing implications
        (3) Document assumptions and dependencies explicitly
        (4) Require written approval for scope modifications
        (5) Implement regular milestone reviews with stakeholder sign-off
        """,
    },
    {
        "doc_type": "policy_clause",
        "jurisdiction": "US",
        "contract_type": "general",
        "risk_tag": "general",
        "version": "1.0",
        "title": "Standard Indemnification Clause",
        "content": """
        MUTUAL INDEMNIFICATION
        Each party (Indemnifying Party) agrees to indemnify, defend, and hold
        harmless the other party from and against any third-party claims arising
        from: (a) breach of this Agreement; (b) negligence or willful misconduct;
        (c) infringement of intellectual property rights. The indemnified party
        shall provide prompt notice and reasonable cooperation.
        """,
    },
]


# ── Document Chunking ────────────────────────────────────────────────────────


def chunk_document(content: str, max_chunk_size: int = 500) -> list[str]:
    """Split document into overlapping chunks for better retrieval.

    Uses sentence-aware chunking with overlap for context preservation.
    """
    # Simple sentence splitting
    import re
    sentences = re.split(r'(?<=[.!?])\s+', content.strip())

    chunks = []
    current_chunk = []
    current_size = 0

    for sentence in sentences:
        sentence_size = len(sentence)

        if current_size + sentence_size <= max_chunk_size:
            current_chunk.append(sentence)
            current_size += sentence_size + 1  # +1 for space
        else:
            if current_chunk:
                chunks.append(" ".join(current_chunk))
            current_chunk = [sentence]
            current_size = sentence_size

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks if chunks else [content]  # Fallback to full content


# ── Bootstrap Functions ──────────────────────────────────────────────────────


async def bootstrap_static_policies(policies: list[dict] | None = None):
    """Ingest policy documents into FAISS vector store."""
    policies = policies or SAMPLE_POLICIES

    logger.info("vector_bootstrap_started", policy_count=len(policies))

    memory = VectorMemoryManager()
    texts = []
    metadatas = []

    for policy in policies:
        # Chunk the document
        chunks = chunk_document(policy["content"])

        for chunk in chunks:
            # Create metadata
            metadata = normalize_static_metadata({
                "doc_type": policy.get("doc_type", "unknown"),
                "jurisdiction": policy.get("jurisdiction", "US"),
                "contract_type": canonical_contract_type(policy.get("contract_type")),
                "risk_tag": policy.get("risk_tag", "general"),
                "version": policy.get("version", "1.0"),
                "title": policy.get("title", "Untitled"),
            })

            texts.append(chunk.strip())
            metadatas.append(metadata)

    # Upsert in batches
    for i in range(0, len(texts), BATCH_SIZE):
        batch_texts = texts[i:i + BATCH_SIZE]
        batch_metadatas = metadatas[i:i + BATCH_SIZE]

        await memory.upsert_static(batch_texts, batch_metadatas)

        logger.info(
            "vector_batch_ingested",
            batch=i // BATCH_SIZE + 1,
            count=len(batch_texts),
        )

    # Verify ingestion
    test_query = "confidentiality obligations NDA"
    results = await memory.search_static(test_query, k=3)

    logger.info(
        "vector_bootstrap_verification",
        query=test_query,
        results_count=len(results),
        top_result_score=results[0]["score"] if results else None,
    )

    await memory.close()

    logger.info(
        "vector_bootstrap_completed",
        total_documents=len(texts),
        total_chunks=len(texts),
    )

    return len(texts)


async def bootstrap_from_directory(directory: Path):
    """Ingest documents from a directory structure.

    Expected structure:
    data/policies/
    ├── nda/
    │   ├── us_general.json
    │   └── eu_gdpr.json
    ├── msa/
    │   └── us_payment_terms.json
    └── compliance/
        └── sox_requirements.json
    """
    if not directory.exists():
        logger.warning("policy_directory_not_found", path=str(directory))
        return 0

    policies = []

    for doc_file in directory.rglob("*.json"):
        try:
            with open(doc_file, "r") as f:
                doc = json.load(f)

            # Infer metadata from path
            parts = doc_file.parts
            contract_type = parts[-2] if len(parts) >= 2 else "general"

            policy = {
                "doc_type": doc.get("doc_type", "policy_clause"),
                "jurisdiction": doc.get("jurisdiction", "US"),
                "contract_type": contract_type,
                "risk_tag": doc.get("risk_tag", "general"),
                "version": doc.get("version", "1.0"),
                "title": doc.get("title", doc_file.stem),
                "content": doc.get("content", ""),
            }
            policies.append(policy)

        except Exception as e:
            logger.warning("policy_load_failed", file=str(doc_file), error=str(e))

    return await bootstrap_static_policies(policies)


# ── CLI Entry Point ──────────────────────────────────────────────────────────


def main():
    """Run the bootstrap script."""
    import asyncio

    print("=" * 60)
    print("NEXUS Vector Memory Bootstrap")
    print("=" * 60)

    # Check for custom policy directory
    policy_dir = os.environ.get("NEXUS_POLICY_DIR")
    if policy_dir:
        policy_path = Path(policy_dir)
        if policy_path.exists():
            print(f"Loading policies from: {policy_path}")
            count = asyncio.run(bootstrap_from_directory(policy_path))
        else:
            print(f"Policy directory not found: {policy_path}")
            print("Falling back to sample policies...")
            count = asyncio.run(bootstrap_static_policies())
    else:
        print("Loading sample policies...")
        count = asyncio.run(bootstrap_static_policies())

    print("=" * 60)
    print(f"Bootstrap complete: {count} document chunks ingested")
    print("=" * 60)


if __name__ == "__main__":
    main()
