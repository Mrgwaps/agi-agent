from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings
from app.models.memory import MemoryFact, MemorySearchResult

logger = logging.getLogger(__name__)


class VectorStore:
    """
    ChromaDB-backed vector store for semantic similarity search.
    Falls back to hash-based in-memory store if ChromaDB is unavailable.
    """

    def __init__(self) -> None:
        self._client: Optional[Any] = None
        self._collection: Optional[Any] = None
        self._use_fallback: bool = False
        self._fallback_store: Dict[str, Tuple[MemoryFact, str]] = {}

    async def _get_collection(self) -> Optional[Any]:
        if self._collection is not None:
            return self._collection
        if self._use_fallback:
            return None

        try:
            import chromadb

            try:
                # Try HTTP client first (production mode)
                self._client = chromadb.HttpClient(
                    host=settings.chroma_host,
                    port=settings.chroma_port,
                )
                self._client.heartbeat()
            except Exception:
                # Fall back to embedded persistent client
                self._client = chromadb.PersistentClient(
                    path=settings.chroma_persist_directory
                )

            self._collection = self._client.get_or_create_collection(
                name=settings.chroma_collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info("VectorStore: connected to ChromaDB")
            return self._collection

        except ImportError:
            logger.warning("chromadb not installed – using hash fallback")
            self._use_fallback = True
            return None
        except Exception as exc:
            logger.warning("VectorStore: ChromaDB unavailable (%s) – using hash fallback", exc)
            self._use_fallback = True
            return None

    # ── Public API ───────────────────────────────────────────────────────────

    async def add_document(self, fact: MemoryFact) -> str:
        """Add or update a fact in the vector store. Returns embedding_id."""
        collection = await self._get_collection()
        text = f"{fact.key}: {fact.value}"
        doc_id = self._make_id(fact.id)

        if collection is None:
            # Fallback: store by hash
            self._fallback_store[doc_id] = (fact, text)
            return doc_id

        try:
            embedding = await self._embed(text)
            metadata = {
                "task_id": fact.taskId or "",
                "key": fact.key,
                "scope": fact.scope.value,
                "fact_id": fact.id,
            }

            if embedding is not None:
                collection.upsert(
                    ids=[doc_id],
                    embeddings=[embedding],
                    documents=[text],
                    metadatas=[metadata],
                )
            else:
                collection.upsert(
                    ids=[doc_id],
                    documents=[text],
                    metadatas=[metadata],
                )
            return doc_id
        except Exception as exc:
            logger.warning("VectorStore.add_document error: %s", exc)
            self._fallback_store[doc_id] = (fact, text)
            return doc_id

    async def search_similar(
        self,
        query: str,
        task_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[MemorySearchResult]:
        collection = await self._get_collection()

        if collection is None:
            return self._fallback_search(query, task_id, limit)

        try:
            where: Optional[Dict[str, Any]] = None
            if task_id:
                where = {"task_id": task_id}

            embedding = await self._embed(query)

            kwargs: Dict[str, Any] = {
                "query_texts": [query],
                "n_results": limit,
                "include": ["documents", "metadatas", "distances"],
            }
            if embedding is not None:
                kwargs["query_embeddings"] = [embedding]
                del kwargs["query_texts"]
            if where:
                kwargs["where"] = where

            results = collection.query(**kwargs)

            facts: List[MemorySearchResult] = []
            ids = results.get("ids", [[]])[0]
            distances = results.get("distances", [[]])[0]
            metadatas = results.get("metadatas", [[]])[0]
            documents = results.get("documents", [[]])[0]

            for i, doc_id in enumerate(ids):
                meta = metadatas[i] if i < len(metadatas) else {}
                dist = distances[i] if i < len(distances) else 1.0
                score = max(0.0, 1.0 - dist)  # cosine distance → similarity

                fact = MemoryFact(
                    id=meta.get("fact_id", doc_id),
                    key=meta.get("key", ""),
                    value=documents[i] if i < len(documents) else "",
                    taskId=meta.get("task_id") or None,
                )
                facts.append(MemorySearchResult(fact=fact, score=score, source="vector"))

            return facts

        except Exception as exc:
            logger.warning("VectorStore.search_similar error: %s", exc)
            return self._fallback_search(query, task_id, limit)

    async def delete_by_task(self, task_id: str) -> int:
        collection = await self._get_collection()
        deleted = 0

        # Fallback cleanup
        keys_to_del = [
            k for k, (f, _) in self._fallback_store.items()
            if f.taskId == task_id
        ]
        for k in keys_to_del:
            del self._fallback_store[k]
            deleted += 1

        if collection is None:
            return deleted

        try:
            collection.delete(where={"task_id": task_id})
            deleted += 1
        except Exception as exc:
            logger.warning("VectorStore.delete_by_task error: %s", exc)

        return deleted

    # ── Internals ────────────────────────────────────────────────────────────

    async def _embed(self, text: str) -> Optional[List[float]]:
        """Try to produce a real embedding; return None to use ChromaDB's default."""
        try:
            import asyncio
            import functools
            from sentence_transformers import SentenceTransformer  # type: ignore

            loop = asyncio.get_running_loop()

            def _encode() -> List[float]:
                model = SentenceTransformer("all-MiniLM-L6-v2")
                return model.encode(text).tolist()

            return await loop.run_in_executor(None, _encode)
        except Exception:
            return None  # ChromaDB will use its own embedding

    def _make_id(self, fact_id: str) -> str:
        return hashlib.md5(fact_id.encode()).hexdigest()

    def _fallback_search(
        self, query: str, task_id: Optional[str], limit: int
    ) -> List[MemorySearchResult]:
        """Simple keyword overlap search for the fallback store."""
        from app.models.memory import MemorySearchResult

        query_words = set(query.lower().split())
        results: List[Tuple[float, MemoryFact]] = []

        for doc_id, (fact, text) in self._fallback_store.items():
            if task_id and fact.taskId != task_id:
                continue
            text_words = set(text.lower().split())
            overlap = len(query_words & text_words)
            if overlap > 0:
                score = overlap / max(len(query_words), 1)
                results.append((score, fact))

        results.sort(key=lambda x: x[0], reverse=True)
        return [
            MemorySearchResult(fact=f, score=s, source="fallback_keyword")
            for s, f in results[:limit]
        ]


# Singleton
vector_store = VectorStore()
