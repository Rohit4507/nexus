"""Memory layer abstractions and utilities."""

from nexus.memory.audit_logger import AuditLogger
from nexus.memory.contract_type_aliases import (
    CONTRACT_TYPE_ALIASES,
    canonical_contract_type,
)
from nexus.memory.vector import (
    ChromaStore,
    FAISSStore,
    OllamaEmbedding,
    STATIC_METADATA_KEYS,
    VectorMemoryManager,
    normalize_static_metadata,
    prepare_static_filter,
    static_metadata_matches,
)

__all__ = [
    "CONTRACT_TYPE_ALIASES",
    "canonical_contract_type",
    "AuditLogger",
    "OllamaEmbedding",
    "FAISSStore",
    "ChromaStore",
    "VectorMemoryManager",
    "STATIC_METADATA_KEYS",
    "normalize_static_metadata",
    "prepare_static_filter",
    "static_metadata_matches",
]
