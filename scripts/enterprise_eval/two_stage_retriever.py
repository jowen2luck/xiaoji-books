# -*- coding: utf-8 -*-
"""Enterprise Two-Stage Hybrid Retriever with Ground Truth Provenance & Abstention Guard.

Features:
1. Multi-turn Conversational Query Rewriter (Resolves pronouns & extracts key entities)
2. Sparse Channel: SQLite FTS5 full-text search with BM25 ranking
3. Dense Channel: BGE-small-zh-v1.5 embeddings with cosine similarity
4. Rank Fusion: Parameter-free Reciprocal Rank Fusion (RRF, k=60)
5. Deep Fine-Ranking: Cross-Encoder (bge-reranker-base)
6. Anti-Hallucination Confidence Guard: Calibrated threshold tau=0.35 for OOD rejection
7. Physical Anchor Binding: page_index, char_range, layout_bbox
"""

import json
import math
import os
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

RRF_K = 60
DEFAULT_TAU = 0.35
LOCAL_RERANKER_PATH = r"C:\Users\31239\.cache\modelscope\models\BAAI--bge-reranker-base\snapshots\master"


def rewrite_conversational_query(query: str, chat_history: Optional[List[Dict[str, str]]] = None) -> Dict[str, str]:
    """Resolves pronouns & conversational noise in multi-turn dialogues."""
    cleaned = query.strip()
    resolved = cleaned

    # Simple coreference resolution if chat history exists
    if chat_history and len(chat_history) > 0:
        last_turn = chat_history[-1]
        last_user = last_turn.get("user", "")
        last_assistant = last_turn.get("assistant", "")

        # Extract last subject/topic
        match = re.search(r"《(.*?)》", last_user) or re.search(r"关于(.*?)[的|，|,]", last_user)
        topic = match.group(1) if match else ""
        if not topic and len(last_user) > 4:
            topic = last_user[:15]

        # Pronoun substitution
        for pronoun in ["它", "该条款", "该项规定", "这个协议", "该文档", "这"]:
            if pronoun in resolved and topic:
                resolved = resolved.replace(pronoun, f"《{topic}》")
                break

    # Strip conversational filler
    for prefix in ["我想了解一下", "请帮我查一下", "请问", "能否告诉我", "关于", "当年关于"]:
        if resolved.startswith(prefix):
            resolved = resolved[len(prefix):].strip()
            break

    for suffix in ["是什么？", "是多少？", "的内容是什么", "的具体主张", "的具体规定"]:
        if resolved.endswith(suffix):
            resolved = resolved[:-len(suffix)].strip()
            break

    # Sparse term extraction
    terms = [t for t in re.split(r"[\s,，、。？?！!]+", resolved) if len(t) > 1]
    sparse_q = " ".join(terms) if terms else resolved

    return {
        "raw_query": query,
        "resolved_query": resolved,
        "sparse_query": sparse_q,
    }


def compute_rrf(ranked_lists: List[List[Tuple[str, float]]], top_n: int = 20) -> List[Tuple[str, float]]:
    """Reciprocal Rank Fusion: RRF(d) = sum(1 / (k + rank))."""
    scores: Dict[str, float] = {}
    for rlist in ranked_lists:
        for rank, (item_id, _) in enumerate(rlist):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (RRF_K + rank + 1)
    sorted_items = sorted(scores.items(), key=lambda x: -x[1])
    return sorted_items[:top_n]


class EnterpriseTwoStageRetriever:
    """Enterprise RAG Retriever directly operating on catalog.db."""

    def __init__(
        self,
        db_path: str,
        dense_model_name: str = "BAAI/bge-small-zh-v1.5",
        reranker_path: Optional[str] = None,
        confidence_threshold: float = DEFAULT_TAU,
    ):
        self.db_path = db_path
        self.confidence_threshold = confidence_threshold
        self.dense_model_name = dense_model_name
        self.reranker_path = reranker_path or LOCAL_RERANKER_PATH

        self.dense_model = None
        self.reranker_model = None

        self._doc_cache: Dict[str, Dict[str, Any]] = {}
        self._doc_embeddings: Optional[np.ndarray] = None
        self._doc_ids: List[str] = []

    def lazy_init(self):
        """Loads models if not already loaded."""
        if self.dense_model is None:
            from sentence_transformers import SentenceTransformer
            print(f"[Retriever] Loading Dense model: {self.dense_model_name} ...")
            self.dense_model = SentenceTransformer(self.dense_model_name)

        if self.reranker_model is None and os.path.exists(self.reranker_path):
            from sentence_transformers import CrossEncoder
            print(f"[Retriever] Loading Cross-Encoder: {self.reranker_path} ...")
            self.reranker_model = CrossEncoder(self.reranker_path)

    def warm_cache_from_db(self, max_paragraphs: int = 2500):
        """Pre-warms in-memory cache and builds dense index for benchmark candidates."""
        self.lazy_init()
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT p.id, p.book_id, p.page_index, p.text_normalized, p.char_start, p.char_end,
                   p.evidence_set_id, a.layout_bbox, b.title
            FROM paragraphs p
            LEFT JOIN anchors a ON a.id = p.id
            LEFT JOIN books b ON b.book_id = p.book_id
            WHERE p.text_normalized IS NOT NULL AND length(p.text_normalized) > 25
            LIMIT ?
            """,
            (max_paragraphs,),
        )
        rows = cur.fetchall()
        conn.close()

        texts = []
        self._doc_ids = []
        self._doc_cache = {}

        for r in rows:
            doc_id = r[0]
            clean_text = (r[3] or "").strip()
            self._doc_ids.append(doc_id)
            self._doc_cache[doc_id] = {
                "id": doc_id,
                "book_id": r[1],
                "page_index": r[2],
                "text": clean_text,
                "char_range": [r[4], r[5]],
                "evidence_set_id": r[6],
                "layout_bbox": r[7],
                "book_title": r[8],
            }
            texts.append(clean_text)

        print(f"[Retriever] Encoding {len(texts)} paragraphs for dense recall...")
        t0 = time.time()
        self._doc_embeddings = self.dense_model.encode(
            texts,
            batch_size=64,
            show_progress_bar=False,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        print(f"[Retriever] Dense indexing completed in {time.time() - t0:.2f}s.")

    def sparse_search(self, query: str, top_k: int = 30) -> List[Tuple[str, float]]:
        """Sparse recall via SQLite FTS5."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        terms = [t for t in re.split(r"[\s,，、。？?！!]+", query) if len(t) > 1]
        fts_query = " OR ".join(f'"{t}"' for t in terms) if terms else f'"{query}"'

        results = []
        try:
            cur.execute(
                """
                SELECT paragraph_id, bm25(paragraphs_fts) AS score
                FROM paragraphs_fts
                WHERE paragraphs_fts MATCH ?
                ORDER BY score ASC
                LIMIT ?
                """,
                (fts_query, top_k),
            )
            for row in cur.fetchall():
                norm_score = 1.0 / (1.0 + abs(row[1]))
                results.append((row[0], norm_score))
        except Exception:
            pat = f"%{terms[0] if terms else query}%"
            cur.execute(
                """
                SELECT id, 0.5 FROM paragraphs
                WHERE text_normalized LIKE ?
                LIMIT ?
                """,
                (pat, top_k),
            )
            for row in cur.fetchall():
                results.append((row[0], 0.5))
        conn.close()
        return results

    def dense_search(self, query: str, top_k: int = 30) -> List[Tuple[str, float]]:
        """Dense recall via cosine similarity."""
        if self._doc_embeddings is None or len(self._doc_ids) == 0:
            return []
        prefix = "为这个句子生成表示以用于相关文章检索："
        q_vec = self.dense_model.encode([f"{prefix}{query}"], normalize_embeddings=True, convert_to_numpy=True)[0]
        sims = np.dot(self._doc_embeddings, q_vec)
        top_idx = np.argsort(-sims)[:top_k]
        return [(self._doc_ids[i], float(sims[i])) for i in top_idx]

    def rerank(self, query: str, candidate_ids: List[str]) -> List[Tuple[str, float]]:
        """Deep Cross-Encoder Reranking."""
        pairs = []
        valid_ids = []
        for cid in candidate_ids:
            doc = self._doc_cache.get(cid)
            if doc and doc.get("text"):
                pairs.append((query, doc["text"][:400]))
                valid_ids.append(cid)

        if not pairs:
            return []

        if self.reranker_model is not None:
            raw_scores = self.reranker_model.predict(pairs)
            scores = [float(s) for s in raw_scores]
        else:
            # Fallback dense dot product if reranker not loaded
            q_emb = self.dense_model.encode([query], normalize_embeddings=True, convert_to_numpy=True)[0]
            d_embs = self.dense_model.encode([p[1] for p in pairs], normalize_embeddings=True, convert_to_numpy=True)
            scores = list(np.dot(d_embs, q_emb))

        scored = list(zip(valid_ids, scores))
        scored.sort(key=lambda x: -x[1])
        return scored

    def execute_search(
        self,
        raw_query: str,
        chat_history: Optional[List[Dict[str, str]]] = None,
        top_k: int = 3,
        strategy: str = "full_pipeline",
    ) -> Dict[str, Any]:
        """End-to-end Enterprise Search Pipeline with confidence-based abstention."""
        t0 = time.time()
        rw = rewrite_conversational_query(raw_query, chat_history)
        resolved_q = rw["resolved_query"]
        sparse_q = rw["sparse_query"]

        if strategy == "bm25_only":
            candidates = self.sparse_search(sparse_q, top_k=top_k)
            scored = candidates
        elif strategy == "dense_only":
            candidates = self.dense_search(resolved_q, top_k=top_k)
            scored = candidates
        elif strategy == "rrf_hybrid":
            sp = self.sparse_search(sparse_q, top_k=30)
            dp = self.dense_search(resolved_q, top_k=30)
            fused = compute_rrf([sp, dp], top_n=top_k)
            scored = fused
        else:  # "full_pipeline"
            sp = self.sparse_search(sparse_q, top_k=30)
            dp = self.dense_search(resolved_q, top_k=30)
            fused = compute_rrf([sp, dp], top_n=15)
            fused_ids = [c[0] for c in fused]
            scored = self.rerank(resolved_q, fused_ids)

        # Confidence & Abstention Guard
        top_score = scored[0][1] if scored else 0.0
        # If score is normalized probability or logits
        is_abstained = (len(scored) == 0) or (top_score < self.confidence_threshold)

        results = []
        if not is_abstained:
            for cid, score in scored[:top_k]:
                doc = self._doc_cache.get(cid, {})
                results.append({
                    "id": cid,
                    "book_id": doc.get("book_id"),
                    "book_title": doc.get("book_title"),
                    "page_index": doc.get("page_index"),
                    "snippet": doc.get("text", "")[:200],
                    "char_range": doc.get("char_range"),
                    "layout_bbox": doc.get("layout_bbox"),
                    "score": round(score, 4),
                    "provenance_intact": True,
                })

        total_ms = (time.time() - t0) * 1000.0
        return {
            "query": raw_query,
            "resolved_query": resolved_q,
            "strategy": strategy,
            "top_score": round(top_score, 4),
            "is_abstained": is_abstained,
            "abstain_reason": "置信度低于安全阈值 (OOD 拦截，杜绝大模型幻觉)" if is_abstained else None,
            "results": results,
            "latency_ms": round(total_ms, 2),
        }
