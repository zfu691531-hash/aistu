# -*- coding: utf-8 -*-
"""Hybrid retrieval implementation."""

from __future__ import annotations

from sqlalchemy.orm import Session

from core.config import settings
from database.models.school_rule_chunk import SchoolRuleChunk
from services.ai.base import ai_client
from services.rag.rule_intent import extract_structured_rule_meta, infer_query_intent, metadata_match_boost
from services.rag.milvus_store import MilvusRuleStore
from services.rag.schema_guard import ensure_rule_rag_schema
from services.rag.vector_utils import bm25_like, dense_vector, normalize_dense_vector, sparse_milvus_vector, tokenize


milvus_store = MilvusRuleStore(
    uri=getattr(settings, "MILVUS_URI", ""),
    token=getattr(settings, "MILVUS_TOKEN", ""),
    collection_name=getattr(settings, "MILVUS_COLLECTION", "school_rule_chunks"),
    dense_dim=getattr(settings, "AI_EMBEDDING_DIM", 1024),
)


def hybrid_search(db: Session, query: str, top_k: int = 5) -> list[dict]:
    ensure_rule_rag_schema()
    query_tokens = tokenize(query)
    query_intent = infer_query_intent(query)
    embedding_rows = ai_client.embed_texts([query], model_name=getattr(settings, "AI_EMBEDDING_MODEL_NAME", "") or None)
    if embedding_rows and embedding_rows[0]:
        query_dense = normalize_dense_vector(embedding_rows[0])
    else:
        query_dense = dense_vector(query_tokens, dims=getattr(settings, "AI_EMBEDDING_DIM", 1024))
    query_sparse = sparse_milvus_vector(query_tokens)
    milvus_scores = milvus_store.search(query_dense, query_sparse, limit=max(top_k * 3, 10))
    rows = []

    for chunk in (
        db.query(SchoolRuleChunk)
        .filter(SchoolRuleChunk.status.in_(["pending", "synced"]))
        .order_by(SchoolRuleChunk.rule_id.asc(), SchoolRuleChunk.chunk_index.asc())
        .all()
    ):
        doc_tokens = tokenize(chunk.chunk_text)
        title_text = (chunk.chunk_text or "").splitlines()[0] if chunk.chunk_text else ""
        title_tokens = tokenize(title_text)
        structured_meta = extract_structured_rule_meta(chunk.chunk_text)
        bm25 = bm25_like(query_tokens, doc_tokens)
        title_boost = bm25_like(query_tokens, title_tokens) * 1.5 if title_tokens else 0.0
        keyword_hits = len(set(query_intent.get("matched_terms") or []).intersection(set(chunk.keywords_json or [])))
        keyword_boost = keyword_hits * 0.25
        structured_boost = metadata_match_boost(query_intent, structured_meta)
        vector_scores = milvus_scores.get(int(chunk.id), {})
        sparse = float(vector_scores.get("sparse", 0.0))
        dense = float(vector_scores.get("dense", 0.0))
        fused = (
            bm25 * 0.42
            + title_boost * 0.18
            + keyword_boost * 0.17
            + structured_boost * 0.15
            + sparse * 0.06
            + dense * 0.02
        )
        if fused <= 0:
            continue
        rows.append(
            {
                "chunk_id": chunk.id,
                "rule_id": chunk.rule_id,
                "rule_version": chunk.rule_version,
                "chunk_text": chunk.chunk_text,
                "scores": {
                    "bm25": round(bm25, 6),
                    "title_boost": round(title_boost, 6),
                    "keyword_boost": round(keyword_boost, 6),
                    "structured_boost": round(structured_boost, 6),
                    "sparse": round(sparse, 6),
                    "dense": round(dense, 6),
                    "fused": round(fused, 6),
                },
            }
        )

    return sorted(rows, key=lambda item: item["scores"]["fused"], reverse=True)[:top_k]
