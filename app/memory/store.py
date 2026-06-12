"""ChromaDB-backed memory store for context retrieval."""

from __future__ import annotations

import os
import json
import hashlib
from typing import Any, Dict, List, Optional
from datetime import datetime

import chromadb
from chromadb.config import Settings as ChromaSettings
from chromadb import Documents, EmbeddingFunction, Embeddings

from app.utils.logging import get_logger

logger = get_logger(__name__)


class _HashEmbeddingFunction(EmbeddingFunction):
    """
    Lightweight deterministic embedding using SHA-256 hashing.
    Used as a fallback when the ONNX model cannot be downloaded
    (e.g. sandboxed CI, air-gapped environments).
    Cosine similarity on these vectors still gives meaningful grouping
    for exact/near-exact matches, though semantic recall is limited.
    In production with internet access, ChromaDB will download and use
    the full all-MiniLM-L6-v2 ONNX model automatically.
    """
    DIM = 256

    def __call__(self, input: Documents) -> Embeddings:
        results = []
        for text in input:
            h = hashlib.sha256(text.lower().encode()).digest()
            vec = [((b / 255.0) - 0.5) * 2 for b in h]  # normalise to [-1, 1]
            # Pad / truncate to DIM
            while len(vec) < self.DIM:
                vec.extend(vec)
            results.append(vec[: self.DIM])
        return results


def _make_embedding_function() -> Optional[EmbeddingFunction]:
    """Return the best available embedding function."""
    try:
        from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2
        ef = ONNXMiniLM_L6_V2()
        # Quick smoke-test to see if the model is available
        ef(["warmup"])
        logger.info("Using ONNXMiniLM_L6_V2 embeddings")
        return ef
    except Exception:
        logger.warning("ONNX embedding model unavailable; using hash-based fallback embeddings")
        return _HashEmbeddingFunction()


class MemoryStore:
    """Manages persistent memory using ChromaDB collections."""

    COLLECTION_EMAILS = "email_threads"
    COLLECTION_DRAFTS = "approved_drafts"
    COLLECTION_STYLE = "writing_style"
    COLLECTION_KNOWLEDGE = "company_knowledge"

    def __init__(self, persist_dir: str = "./data/chroma"):
        os.makedirs(persist_dir, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._ef = _make_embedding_function()
        self._collections: Dict[str, Any] = {}
        self._init_collections()

    def _init_collections(self):
        for name in [
            self.COLLECTION_EMAILS,
            self.COLLECTION_DRAFTS,
            self.COLLECTION_STYLE,
            self.COLLECTION_KNOWLEDGE,
        ]:
            self._collections[name] = self._client.get_or_create_collection(
                name=name,
                metadata={"hnsw:space": "cosine"},
                embedding_function=self._ef,
            )
        logger.info("ChromaDB collections initialized")

    # ─── Email Threads ──────────────────────────────────────────────────────────

    def store_email_thread(
        self,
        thread_id: str,
        subject: str,
        participants: List[str],
        messages_summary: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        col = self._collections[self.COLLECTION_EMAILS]
        meta = {
            "thread_id": thread_id,
            "subject": subject,
            "participants": json.dumps(participants),
            "stored_at": datetime.utcnow().isoformat(),
        }
        if metadata:
            meta.update({k: str(v) for k, v in metadata.items()})
        col.upsert(
            ids=[thread_id],
            documents=[messages_summary],
            metadatas=[meta],
        )

    def retrieve_similar_threads(
        self, query: str, n_results: int = 3
    ) -> List[Dict[str, Any]]:
        col = self._collections[self.COLLECTION_EMAILS]
        try:
            results = col.query(
                query_texts=[query],
                n_results=min(n_results, col.count() or 1),
            )
            items = []
            for i, doc in enumerate(results["documents"][0]):
                items.append({
                    "document": doc,
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i],
                })
            return items
        except Exception as e:
            logger.warning("Thread retrieval failed", error=str(e))
            return []

    # ─── Approved Drafts ────────────────────────────────────────────────────────

    def store_approved_draft(
        self,
        draft_id: str,
        email_category: str,
        original_subject: str,
        approved_body: str,
    ) -> None:
        col = self._collections[self.COLLECTION_DRAFTS]
        doc = f"Category: {email_category}\nSubject: {original_subject}\nResponse: {approved_body}"
        col.upsert(
            ids=[draft_id],
            documents=[doc],
            metadatas=[{
                "draft_id": draft_id,
                "category": email_category,
                "subject": original_subject,
                "stored_at": datetime.utcnow().isoformat(),
            }],
        )

    def retrieve_similar_responses(
        self, query: str, category: str = "", n_results: int = 3
    ) -> List[str]:
        col = self._collections[self.COLLECTION_DRAFTS]
        try:
            where = {"category": category} if category else None
            results = col.query(
                query_texts=[query],
                n_results=min(n_results, col.count() or 1),
                where=where,
            )
            return results["documents"][0] if results["documents"] else []
        except Exception as e:
            logger.warning("Draft retrieval failed", error=str(e))
            return []

    # ─── Company Knowledge ──────────────────────────────────────────────────────

    def store_knowledge(self, key: str, content: str, metadata: Optional[Dict] = None) -> None:
        col = self._collections[self.COLLECTION_KNOWLEDGE]
        meta = {"key": key, "stored_at": datetime.utcnow().isoformat()}
        if metadata:
            meta.update({k: str(v) for k, v in metadata.items()})
        col.upsert(ids=[key], documents=[content], metadatas=[meta])

    def retrieve_knowledge(self, query: str, n_results: int = 3) -> List[str]:
        col = self._collections[self.COLLECTION_KNOWLEDGE]
        try:
            results = col.query(
                query_texts=[query],
                n_results=min(n_results, col.count() or 1),
            )
            return results["documents"][0] if results["documents"] else []
        except Exception as e:
            logger.warning("Knowledge retrieval failed", error=str(e))
            return []

    # ─── Writing Style ──────────────────────────────────────────────────────────

    def store_writing_style(self, user_email: str, style_notes: str) -> None:
        col = self._collections[self.COLLECTION_STYLE]
        col.upsert(
            ids=[user_email],
            documents=[style_notes],
            metadatas=[{"user_email": user_email, "updated_at": datetime.utcnow().isoformat()}],
        )

    def get_writing_style(self, user_email: str) -> str:
        col = self._collections[self.COLLECTION_STYLE]
        try:
            result = col.get(ids=[user_email])
            docs = result.get("documents", [])
            return docs[0] if docs else ""
        except Exception:
            return ""
