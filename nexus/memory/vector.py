"""Vector memory layer with FAISS (static) and ChromaDB (dynamic).

This module provides a unified ``VectorMemoryManager`` that routes writes and
queries to:
  - FAISS for static corpora (policies, templates, SOPs)
  - ChromaDB for dynamic corpora (meetings, vendor updates, execution traces)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from abc import ABC, abstractmethod
from typing import Any

import chromadb
import faiss
import httpx
import structlog

from nexus.memory.contract_type_aliases import canonical_contract_type

logger = structlog.get_logger()

# Required metadata for every static (FAISS) chunk — used for governance and filtered retrieval.
STATIC_METADATA_KEYS: tuple[str, ...] = (
    "doc_type",
    "jurisdiction",
    "contract_type",
    "risk_tag",
    "version",
)


def normalize_static_metadata(meta: dict | None) -> dict[str, str]:
    """Ensure all five static keys exist; normalize for consistent matching."""
    m = meta or {}
    out: dict[str, str] = {}
    out["doc_type"] = str(m.get("doc_type", "unknown")).strip().lower()
    out["jurisdiction"] = str(m.get("jurisdiction", "US")).strip()
    out["contract_type"] = canonical_contract_type(m.get("contract_type"))
    out["risk_tag"] = str(m.get("risk_tag", "general")).strip().lower()
    out["version"] = str(m.get("version", "1.0")).strip()
    return out


def static_metadata_matches(stored_meta: dict | None, filt: dict | None) -> bool:
    """AND match on keys present in ``filt``. Use value ``*`` to skip that dimension."""
    if not filt:
        return True
    norm_stored = normalize_static_metadata(stored_meta)
    for key, want in filt.items():
        if key not in STATIC_METADATA_KEYS:
            continue
        if want in (None, "*"):
            continue
        got = str(norm_stored.get(key, "")).strip()
        exp = str(want).strip()
        if key == "version":
            if got != exp:
                return False
        else:
            if got.casefold() != exp.casefold():
                return False
    return True


def prepare_static_filter(raw: dict | None) -> dict[str, str] | None:
    """Build a filter from explicit keys only (no default-fill). Values ``*`` = wildcard."""
    if not raw:
        return None
    out: dict[str, str] = {}
    for key in STATIC_METADATA_KEYS:
        if key not in raw:
            continue
        v = raw[key]
        if v in (None, "*"):
            out[key] = "*"
        elif key == "contract_type":
            out[key] = canonical_contract_type(v)
        elif key in ("doc_type", "risk_tag"):
            out[key] = str(v).strip().lower()
        else:
            out[key] = str(v).strip()
    return out or None


class VectorStore(ABC):
    """Base abstraction for vector databases."""

    @abstractmethod
    async def add_texts(self, texts: list[str], metadatas: list[dict] | None = None) -> None:
        pass

    @abstractmethod
    async def similarity_search(self, query: str, k: int = 5) -> list[dict]:
        pass

    async def close(self) -> None:
        """Close any underlying clients/resources."""
        return None


class OllamaEmbedding:
    """Local embeddings via Ollama."""

    def __init__(self, model: str = "nomic-embed-text", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.http = httpx.AsyncClient(timeout=30.0)

    async def embed_query(self, text: str) -> list[float]:
        resp = await self.http.post(
            f"{self.base_url}/api/embeddings",
            json={"model": self.model, "prompt": text},
        )
        resp.raise_for_status()
        return resp.json().get("embedding", [])

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        # Naive sequential implementation for simplicity.
        # Production would use batch endpoints or concurrent tasks.
        embeddings = []
        for text in texts:
            emb = await self.embed_query(text)
            embeddings.append(emb)
        return embeddings

    async def close(self):
        await self.http.aclose()


class FAISSStore(VectorStore):
    """FAISS Backend for static datasets (e.g., standard contract clauses).
    
    Loads pre-computed `.index` files fully into RAM for zero-latency lookups.
    """

    def __init__(self, index_path: str, embedding_dims: int = 768):
        self.index_path = index_path
        self.meta_path = f"{index_path}.meta.json"
        self.embedding_dims = embedding_dims
        self._embedder = OllamaEmbedding()
        
        # In-memory mapping of vector IDs to actual text content
        # For FAISS, we typically store this mapping in a SQLite DB or JSON.
        # Here we mock it as a dict for simplicity of the abstraction.
        self._store: dict[int, dict] = self._load_metadata_store()
        self._current_id = max(self._store.keys(), default=-1) + 1

        if os.path.exists(index_path):
            self.index = faiss.read_index(index_path)
            logger.info("faiss_index_loaded", path=index_path, count=self.index.ntotal)
        else:
            # IndexFlatL2 is exact search (L2 distance)
            self.index = faiss.IndexFlatL2(embedding_dims)
            logger.info("faiss_index_created", dims=embedding_dims)

    def _load_metadata_store(self) -> dict[int, dict]:
        if not os.path.exists(self.meta_path):
            return {}
        try:
            with open(self.meta_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            out: dict[int, dict] = {}
            for k, v in raw.items():
                entry = dict(v)
                if "metadata" in entry:
                    entry["metadata"] = normalize_static_metadata(entry["metadata"])
                else:
                    entry["metadata"] = normalize_static_metadata({})
                out[int(k)] = entry
            return out
        except Exception as exc:
            logger.warning("faiss_meta_load_failed", error=str(exc), path=self.meta_path)
            return {}

    def _persist_metadata_store(self) -> None:
        Path(self.meta_path).parent.mkdir(parents=True, exist_ok=True)
        payload = {str(k): v for k, v in self._store.items()}
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(payload, f)

    async def add_texts(self, texts: list[str], metadatas: list[dict] | None = None) -> None:
        """Add texts to FAISS (usually done during system bootstrap)."""
        import numpy as np

        embeddings = await self._embedder.embed_documents(texts)
        if not embeddings:
            return

        embs_np = np.array(embeddings).astype("float32")
        self.index.add(embs_np)

        for i, text in enumerate(texts):
            raw_meta = metadatas[i] if metadatas else {}
            meta = normalize_static_metadata(raw_meta)
            self._store[self._current_id] = {"text": text, "metadata": meta}
            self._current_id += 1

        # Optionally save to disk
        Path(self.index_path).parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self.index, self.index_path)
        self._persist_metadata_store()
        logger.info("faiss_texts_added", count=len(texts))

    async def similarity_search(
        self,
        query: str,
        k: int = 5,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict]:
        """Search FAISS by L2 distance; optional post-filter on the five static keys."""
        import numpy as np

        query_emb = await self._embedder.embed_query(query)
        if not query_emb:
            return []

        ntotal = int(self.index.ntotal)
        if ntotal == 0:
            return []

        fetch_k = ntotal if metadata_filter else min(k, ntotal)
        query_np = np.array([query_emb]).astype("float32")
        distances, indices = self.index.search(query_np, fetch_k)

        candidates: list[tuple[float, int]] = []
        for i in range(len(indices[0])):
            idx = int(indices[0][i])
            if idx < 0 or idx not in self._store:
                continue
            meta = self._store[idx]["metadata"]
            if metadata_filter and not static_metadata_matches(meta, metadata_filter):
                continue
            candidates.append((float(distances[0][i]), idx))

        candidates.sort(key=lambda x: x[0])
        results: list[dict] = []
        for dist, idx in candidates[:k]:
            meta = self._store[idx]["metadata"]
            results.append({
                "text": self._store[idx]["text"],
                "metadata": normalize_static_metadata(meta),
                "score": dist,
            })
        return results

    async def close(self) -> None:
        await self._embedder.close()


class ChromaStore(VectorStore):
    """ChromaDB Backend for dynamic datasets (e.g., meeting transcripts, vendor history).
    
    Mounted to a persistent volume, supports concurrent writes and filtering.
    """

    def __init__(self, persist_dir: str = "./chroma_db", collection_name: str = "nexus_dynamic"):
        self.client = chromadb.PersistentClient(path=persist_dir)
        self._embedder = OllamaEmbedding()
        
        # Get or create collection
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )
        logger.info(
            "chroma_collection_ready", 
            name=collection_name, 
            count=self.collection.count()
        )

    async def add_texts(self, texts: list[str], metadatas: list[dict] | None = None) -> None:
        import uuid
        
        embeddings = await self._embedder.embed_documents(texts)
        if not embeddings:
            return
            
        ids = [str(uuid.uuid4()) for _ in texts]
        
        # Ensure metadatas exist natively so Chroma doesn't fail
        if not metadatas:
            metadatas = [{"source": "unknown"} for _ in texts]
            
        # ChromaDB API is synchronous, but fast locally
        self.collection.add(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=texts
        )
        logger.info("chroma_texts_added", count=len(texts))

    async def similarity_search(self, query: str, k: int = 5) -> list[dict]:
        query_emb = await self._embedder.embed_query(query)
        if not query_emb:
            return []

        # Chroma search
        results = self.collection.query(
            query_embeddings=[query_emb],
            n_results=k,
            include=["documents", "metadatas", "distances"]
        )
        
        parsed_results = []
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        dists = results.get("distances", [[]])[0]
        
        for i in range(len(docs)):
            parsed_results.append({
                "text": docs[i],
                "metadata": metas[i] if metas else {},
                "score": float(dists[i]) if dists else 0.0,
            })
            
        return parsed_results

    async def close(self) -> None:
        await self._embedder.close()


class VectorMemoryManager:
    """Unified vector memory manager for static and dynamic knowledge.

    ``upsert_static`` should be used during bootstrap/indexing workflows.
    ``upsert_dynamic`` is used for runtime data such as meeting transcripts.
    """

    def __init__(
        self,
        faiss_store: FAISSStore | None = None,
        chroma_store: ChromaStore | None = None,
    ):
        self.faiss = faiss_store or FAISSStore(index_path="./data/faiss/static.index")
        self.chroma = chroma_store or ChromaStore(
            persist_dir="./data/chroma",
            collection_name="nexus_dynamic",
        )

    async def upsert_static(
        self,
        texts: list[str],
        metadatas: list[dict] | None = None,
    ) -> None:
        if not texts:
            return
        if metadatas is None:
            metadatas = [normalize_static_metadata({}) for _ in texts]
        else:
            metadatas = [normalize_static_metadata(m) for m in metadatas]
        await self.faiss.add_texts(texts=texts, metadatas=metadatas)
        logger.info("memory_static_upserted", count=len(texts))

    async def upsert_dynamic(
        self,
        texts: list[str],
        metadatas: list[dict] | None = None,
    ) -> None:
        if not texts:
            return
        await self.chroma.add_texts(texts=texts, metadatas=metadatas)
        logger.info("memory_dynamic_upserted", count=len(texts))

    async def search_static(
        self,
        query: str,
        k: int = 5,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict]:
        """Retrieve from static FAISS; ``metadata_filter`` may include the five static keys."""
        filt = prepare_static_filter(metadata_filter)
        primary = await self.faiss.similarity_search(
            query=query, k=k, metadata_filter=filt
        )
        if primary or not filt:
            return primary
        relaxed = dict(filt)
        relaxed["version"] = "*"
        out = await self.faiss.similarity_search(
            query=query, k=k, metadata_filter=prepare_static_filter(relaxed)
        )
        if out:
            return out
        return await self.faiss.similarity_search(query=query, k=k, metadata_filter=None)

    async def search_dynamic(self, query: str, k: int = 5) -> list[dict]:
        return await self.chroma.similarity_search(query=query, k=k)

    async def search_hybrid(
        self,
        query: str,
        k_static: int = 3,
        k_dynamic: int = 5,
    ) -> dict[str, list[dict]]:
        static_hits = await self.search_static(query=query, k=k_static)
        dynamic_hits = await self.search_dynamic(query=query, k=k_dynamic)
        return {"static": static_hits, "dynamic": dynamic_hits}

    async def close(self) -> None:
        await self.faiss.close()
        await self.chroma.close()
