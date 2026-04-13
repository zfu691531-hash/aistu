# -*- coding: utf-8 -*-
"""Knowledge sync service for rule RAG."""

from __future__ import annotations

from sqlalchemy.orm import Session

from core.config import settings
from core.response import error_response, success_response
from database.models.knowledge_sync_task import KnowledgeSyncTask
from database.models.school_rule import SchoolRule
from database.models.school_rule_chunk import SchoolRuleChunk
from services.ai.base import ai_client
from services.rag.milvus_store import MilvusRuleStore
from services.rag.schema_guard import ensure_rule_rag_schema
from services.rag.rule_intent import extract_structured_terms_for_keywords
from services.rag.vector_utils import dense_vector, normalize_dense_vector, sparse_milvus_vector, tokenize
from utils.logger import logger


milvus_store = MilvusRuleStore(
    uri=getattr(settings, "MILVUS_URI", ""),
    token=getattr(settings, "MILVUS_TOKEN", ""),
    collection_name=getattr(settings, "MILVUS_COLLECTION", "school_rule_chunks"),
    dense_dim=getattr(settings, "AI_EMBEDDING_DIM", 1024),
)


def rebuild_rule_index(db: Session, rule_id: int) -> dict:
    ensure_rule_rag_schema()
    rule = db.query(SchoolRule).filter(SchoolRule.id == rule_id).first()
    if not rule:
        return error_response(msg="校规不存在")

    task = KnowledgeSyncTask(rule_id=rule_id, task_type="single", status="running", payload_json={"rule_id": rule_id})
    db.add(task)
    db.commit()
    db.refresh(task)

    try:
        old_chunks = db.query(SchoolRuleChunk).filter(SchoolRuleChunk.rule_id == rule.id).all()
        next_version = max([item.rule_version for item in old_chunks], default=0) + 1
        db.query(SchoolRuleChunk).filter(SchoolRuleChunk.rule_id == rule.id).delete(synchronize_session=False)
        milvus_store.delete_rule_chunks(rule.id)

        chunks = _chunk_rule(rule.category, rule.title, rule.content)
        embedding_vectors = ai_client.embed_texts(
            chunks,
            model_name=getattr(settings, "AI_EMBEDDING_MODEL_NAME", "") or None,
        )
        saved_rows = []
        for index, text in enumerate(chunks):
            token_list = tokenize(text)
            structured_terms = extract_structured_terms_for_keywords(text, category=rule.category)
            keyword_terms = list(dict.fromkeys(token_list[:20] + structured_terms))
            if len(embedding_vectors) == len(chunks) and embedding_vectors[index]:
                dense_row = normalize_dense_vector(embedding_vectors[index])
                dense_model_name = getattr(settings, "AI_EMBEDDING_MODEL_NAME", "") or "remote-embedding"
            else:
                dense_row = dense_vector(token_list, dims=getattr(settings, "AI_EMBEDDING_DIM", 1024))
                dense_model_name = "hash-dense-fallback"
            chunk = SchoolRuleChunk(
                rule_id=rule.id,
                rule_version=next_version,
                chunk_index=index,
                chunk_text=text,
                keywords_json=keyword_terms,
                sparse_vector_meta_json={"token_count": len(token_list)},
                dense_model_name=dense_model_name,
                sparse_model_name="token-counter-v1",
                milvus_collection=milvus_store.collection_name,
                status="pending",
            )
            db.add(chunk)
            db.flush()
            chunk.milvus_pk = str(chunk.id)
            saved_rows.append(
                {
                    "chunk_id": chunk.id,
                    "rule_id": rule.id,
                    "rule_version": next_version,
                    "chunk_text": text,
                    "dense_vector": dense_row,
                    "sparse_vector": sparse_milvus_vector(token_list),
                }
            )

        db.commit()
        milvus_result = milvus_store.upsert_chunks(saved_rows)
        db.query(SchoolRuleChunk).filter(SchoolRuleChunk.rule_id == rule.id).update(
            {"status": "synced" if milvus_result.get("enabled") else "pending"},
            synchronize_session=False,
        )
        task.status = "success"
        task.result_json = {"chunk_count": len(saved_rows), "milvus": milvus_result}
        db.commit()
        return success_response(
            msg="知识库重建成功",
            data={"task_id": task.id, "chunk_count": len(saved_rows), "milvus": milvus_result},
        )
    except Exception as exc:  # pragma: no cover
        task.status = "failed"
        task.error_message = str(exc)
        db.commit()
        logger.exception("rule kb rebuild failed: %s", exc)
        return error_response(msg=f"知识库重建失败: {exc}")


def rebuild_all_indexes(db: Session) -> dict:
    ensure_rule_rag_schema()
    milvus_reset = milvus_store.recreate_collection()
    rules = db.query(SchoolRule).all()
    results = [rebuild_rule_index(db, rule.id) for rule in rules]
    return success_response(
        data={"total": len(results), "results": results, "milvus": milvus_reset},
        msg="全量重建已执行",
    )


def delete_rule_index(db: Session, rule_id: int) -> None:
    ensure_rule_rag_schema()
    db.query(SchoolRuleChunk).filter(SchoolRuleChunk.rule_id == rule_id).delete(synchronize_session=False)
    db.commit()
    milvus_store.delete_rule_chunks(rule_id)


def _chunk_rule(category: str, title: str, content: str, chunk_size: int = 240) -> list[str]:
    text = f"分类: {category}\n标题: {title}\n{content}".strip()
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    current = []
    current_len = 0
    for paragraph in [item.strip() for item in text.splitlines() if item.strip()]:
        if current_len + len(paragraph) > chunk_size and current:
            chunks.append("\n".join(current))
            current = [paragraph]
            current_len = len(paragraph)
        else:
            current.append(paragraph)
            current_len += len(paragraph)
    if current:
        chunks.append("\n".join(current))
    return chunks
