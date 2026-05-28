"""
Hybrid RAG retriever — dense vectors + BM25 keyword search, fused via
Reciprocal Rank Fusion (RRF).

Search strategy by collection
──────────────────────────────
policies_playbooks  : hybrid (semantic + BM25) — policies have exact terminology
                      that keyword search catches reliably; semantic handles
                      paraphrase / intent queries.
campaign_history    : semantic only — prose summaries of past actions.
telemetry_aggregates: semantic only — narrative metric summaries.

Historical performance *data* (time-series, exact values) is NOT retrieved
through RAG — agents use the structured `query_telemetry_aggregates` SQL tool
in agent/tools.py instead.

Retrieval result cache
──────────────────────
Results are cached in-process (LRU, 256 entries) keyed by
(query, tuple(collections), n_results, campaign_id).  This avoids
redundant embedding + ChromaDB round-trips for identical queries within
a workflow run (e.g., the same policy context requested by both analyst
and optimizer nodes for the same goal).

Prompt-caching note
───────────────────
Static policy documents are also good candidates for Anthropic's server-side
prompt caching (beta `cache_control` blocks).  The LLM nodes in
agent/nodes/optimizer.py and auditor.py should mark the RAG context block with
`{"type": "ephemeral"}` when the context is identical across turns to avoid
re-processing the 2 k-token grounding block on every call.
"""
from __future__ import annotations

import glob
import hashlib
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
from rank_bm25 import BM25Okapi

from config import settings
from rag.chunker import chunk_markdown

DOCS_DIR = Path(__file__).parent / "documents"

COLLECTION_POLICIES        = "policies_playbooks"
COLLECTION_CAMPAIGN_HISTORY = "campaign_history"
COLLECTION_TELEMETRY        = "telemetry_aggregates"

# Collections where BM25 keyword search supplements dense retrieval
_HYBRID_COLLECTIONS = {COLLECTION_POLICIES}


# ── ChromaDB helpers ──────────────────────────────────────────────────────────

def _get_client():
    return chromadb.PersistentClient(path=settings.chroma_path)


def _get_or_create_collection(client, name: str):
    return client.get_or_create_collection(
        name=name,
        embedding_function=DefaultEmbeddingFunction(),
        metadata={"hnsw:space": "cosine"},
    )


# ── In-memory BM25 index (rebuilt when policy docs are re-indexed) ────────────

class _BM25Index:
    """Lightweight BM25 index over a flat list of (doc_id, text) pairs."""

    def __init__(self):
        self._ids:   list[str] = []
        self._texts: list[str] = []
        self._bm25: BM25Okapi | None = None

    def build(self, ids: list[str], texts: list[str]) -> None:
        self._ids   = ids
        self._texts = texts
        tokenised   = [_tokenise(t) for t in texts]
        self._bm25  = BM25Okapi(tokenised)

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        """Return [(doc_id, bm25_score), ...] sorted descending."""
        if self._bm25 is None or not self._ids:
            return []
        scores = self._bm25.get_scores(_tokenise(query))
        ranked = sorted(zip(self._ids, scores), key=lambda x: x[1], reverse=True)
        return [(doc_id, score) for doc_id, score in ranked[:top_k] if score > 0]


_policy_bm25 = _BM25Index()


def _tokenise(text: str) -> list[str]:
    """Lower-case, strip punctuation, split on whitespace."""
    return re.sub(r"[^a-z0-9\s_]", " ", text.lower()).split()


# ── Indexing ──────────────────────────────────────────────────────────────────

def index_policy_documents() -> int:
    """
    Re-index all markdown policy docs using structure-aware chunking.
    Rebuilds the in-memory BM25 index after upsert.
    """
    client = _get_client()
    collection = _get_or_create_collection(client, COLLECTION_POLICIES)

    doc_files = glob.glob(str(DOCS_DIR / "*.md"))
    ids, docs, metas = [], [], []

    for filepath in doc_files:
        with open(filepath) as f:
            content = f.read()
        source = Path(filepath).stem

        # Structure-aware chunking preserves heading context per chunk
        chunks = chunk_markdown(content, source=source)
        for i, chunk in enumerate(chunks):
            chunk_id = hashlib.sha256(
                f"{source}:{i}:{chunk.text[:60]}".encode()
            ).hexdigest()[:16]
            ids.append(chunk_id)
            docs.append(chunk.text)
            metas.append({
                "source":       source,
                "chunk_index":  i,
                "chunk_type":   chunk.chunk_type,
                "heading_path": chunk.heading_path,
                "doc_type":     "policy",
            })

    if ids:
        collection.upsert(ids=ids, documents=docs, metadatas=metas)

    # Rebuild BM25 index over the full policy corpus
    _policy_bm25.build(ids, docs)
    # Invalidate retrieval cache since the corpus changed
    _cached_retrieve.cache_clear()

    return len(ids)


def add_campaign_memory(
    campaign_id: str, event_type: str, content: str, metadata: dict | None = None
) -> None:
    client = _get_client()
    collection = _get_or_create_collection(client, COLLECTION_CAMPAIGN_HISTORY)
    event_id = hashlib.sha256(
        f"{campaign_id}:{event_type}:{content[:50]}".encode()
    ).hexdigest()[:16]
    meta = {"campaign_id": campaign_id, "event_type": event_type,
            "doc_type": "campaign_history"}
    if metadata:
        meta.update(metadata)
    collection.upsert(ids=[event_id], documents=[content], metadatas=[meta])
    _cached_retrieve.cache_clear()


def add_telemetry_aggregate(
    campaign_id: str, metric_summary: str, metadata: dict | None = None
) -> None:
    client = _get_client()
    collection = _get_or_create_collection(client, COLLECTION_TELEMETRY)
    agg_id = hashlib.sha256(
        f"{campaign_id}:agg:{metric_summary[:50]}".encode()
    ).hexdigest()[:16]
    meta = {"campaign_id": campaign_id, "doc_type": "telemetry"}
    if metadata:
        meta.update(metadata)
    collection.upsert(ids=[agg_id], documents=[metric_summary], metadatas=[meta])
    _cached_retrieve.cache_clear()


# ── Retrieval ─────────────────────────────────────────────────────────────────

try:
    from langsmith import traceable as _traceable
except ImportError:
    def _traceable(**_kw):   # type: ignore[misc]
        def _wrap(fn): return fn
        return _wrap


@_traceable(
    run_type="retriever",
    name="rag_retrieve",
    metadata={"strategy": "hybrid-rrf", "collections": "policies+history+telemetry"},
)
def retrieve(
    query: str,
    collections: list[str] | None = None,
    n_results: int = 5,
    campaign_id: Optional[str] = None,
) -> list[dict]:
    """
    Multi-collection hybrid retrieval.

    For *policies_playbooks*: fuses dense cosine results with BM25 keyword
    results using Reciprocal Rank Fusion (RRF, k=60).

    For other collections: dense-only (semantic similarity).

    Results are de-duplicated by content hash and sorted by fused score.

    Decorated with @traceable so every call (cache hit or miss) appears as a
    child run in LangSmith under the parent node's trace, capturing query,
    collections, n_results, result count, and latency.
    """
    coll_key = tuple(collections) if collections else ()
    return _cached_retrieve(query, coll_key, n_results, campaign_id)


@lru_cache(maxsize=256)
def _cached_retrieve(
    query: str,
    collections: tuple[str, ...],
    n_results: int,
    campaign_id: Optional[str],
) -> list[dict]:
    coll_list = list(collections) if collections else [
        COLLECTION_POLICIES, COLLECTION_CAMPAIGN_HISTORY, COLLECTION_TELEMETRY
    ]
    client = _get_client()
    all_results: list[dict] = []

    for coll_name in coll_list:
        try:
            collection = client.get_collection(
                name=coll_name,
                embedding_function=DefaultEmbeddingFunction(),
            )
        except Exception:
            continue

        where = None
        if campaign_id and coll_name != COLLECTION_POLICIES:
            where = {"campaign_id": campaign_id}

        # ── Dense retrieval ───────────────────────────────────────────────────
        dense_results: list[dict] = []
        try:
            res = collection.query(
                query_texts=[query],
                n_results=min(n_results * 2, max(collection.count(), 1)),
                where=where,
                include=["documents", "metadatas", "distances"],
            )
            for doc, meta, dist in zip(
                res["documents"][0], res["metadatas"][0], res["distances"][0]
            ):
                dense_results.append({
                    "content":          doc,
                    "source":           meta.get("source", coll_name),
                    "collection":       coll_name,
                    "metadata":         meta,
                    "relevance_score":  1.0 - float(dist),
                    "chunk_type":       meta.get("chunk_type", "paragraph"),
                    "heading_path":     meta.get("heading_path", ""),
                })
        except Exception:
            pass

        # ── BM25 keyword retrieval (policy collection only) ───────────────────
        bm25_results: list[dict] = []
        if coll_name in _HYBRID_COLLECTIONS:
            for doc_id, bm25_score in _policy_bm25.search(query, top_k=n_results * 2):
                # Look up the full document from ChromaDB by id
                try:
                    fetched = collection.get(
                        ids=[doc_id],
                        include=["documents", "metadatas"],
                    )
                    if fetched["ids"]:
                        doc  = fetched["documents"][0]
                        meta = fetched["metadatas"][0]
                        bm25_results.append({
                            "content":      doc,
                            "source":       meta.get("source", coll_name),
                            "collection":   coll_name,
                            "metadata":     meta,
                            "relevance_score": 0.0,  # will be set by RRF
                            "chunk_type":   meta.get("chunk_type", "paragraph"),
                            "heading_path": meta.get("heading_path", ""),
                            "_bm25_score":  bm25_score,
                        })
                except Exception:
                    pass

        if bm25_results:
            fused = _reciprocal_rank_fusion(dense_results, bm25_results)
            all_results.extend(fused)
        else:
            all_results.extend(dense_results)

    # De-duplicate by content hash, keep highest score
    seen: dict[str, dict] = {}
    for r in all_results:
        h = hashlib.sha256(r["content"].encode()).hexdigest()
        if h not in seen or r["relevance_score"] > seen[h]["relevance_score"]:
            seen[h] = r

    return sorted(seen.values(), key=lambda x: x["relevance_score"], reverse=True)[:n_results]


def _reciprocal_rank_fusion(
    dense: list[dict],
    keyword: list[dict],
    k: int = 60,
) -> list[dict]:
    """
    Fuse two ranked lists using Reciprocal Rank Fusion.

    RRF score = Σ 1 / (k + rank_i)

    Results from both lists are indexed by content hash; the fused score
    replaces `relevance_score` on the returned dicts.
    """
    scores: dict[str, float] = {}
    docs:   dict[str, dict]  = {}

    for rank, item in enumerate(dense, start=1):
        h = hashlib.sha256(item["content"].encode()).hexdigest()
        scores[h] = scores.get(h, 0.0) + 1.0 / (k + rank)
        docs[h]   = item

    for rank, item in enumerate(keyword, start=1):
        h = hashlib.sha256(item["content"].encode()).hexdigest()
        scores[h] = scores.get(h, 0.0) + 1.0 / (k + rank)
        if h not in docs:
            docs[h] = item

    fused = []
    for h, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
        result = {**docs[h], "relevance_score": score, "retrieval_method": "rrf"}
        fused.append(result)
    return fused


# ── Context formatting ────────────────────────────────────────────────────────

def format_context_for_prompt(results: list[dict]) -> str:
    """
    Format retrieval results into a grounding context block.

    Includes source, heading path, retrieval method, and relevance score so
    the LLM can cite its reasoning back to specific policy sections.
    """
    if not results:
        return "No relevant policy/history context found."
    parts = []
    for i, r in enumerate(results, 1):
        method = r.get("retrieval_method", "dense")
        path   = r.get("heading_path", "")
        header = (
            f"[Source {i}: {r['source']}"
            + (f" › {path}" if path else "")
            + f" | score={r['relevance_score']:.3f} | method={method}]"
        )
        parts.append(f"{header}\n{r['content']}")
    return "\n\n---\n\n".join(parts)
