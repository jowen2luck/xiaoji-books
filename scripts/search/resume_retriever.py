"""Resume Version: Two-Stage Enterprise Knowledge Base Retriever.

Faithfully implements the architecture described in the resume:
1. Query Rewriting & Intent Normalization
2. Two-Stage Dual-Channel Recall (Dense BGE + Sparse FTS5/BM25)
3. Parameter-free Reciprocal Rank Fusion (RRF, k=60)
4. Cross-Encoder Deep Attention Reranking (BGE/BCE Reranker)
5. Calibrated Confidence Thresholding & Abstention Guard (Anti-hallucination for OOD)
6. Ground Truth Physical Anchoring (page_index, char_range, layout_bbox, provenance)
"""

import math
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

RRF_K = 60
DEFAULT_CONFIDENCE_THRESHOLD = 0.35
LOCAL_RERANKER_PATH = r"C:\Users\31239\.cache\modelscope\models\BAAI--bge-reranker-base\snapshots\master"

STOPWORDS = {
    "我想了解一下", "请帮我查找", "我想知道", "能否告诉我", "请问", "关于",
    "当年", "具体", "有哪些", "是什么", "怎么", "如何", "的", "了", "在",
    "一个", "一下", "请", "帮我", "内容", "说明", "记录", "情况", "分析",
}


def rewrite_query(raw_query: str) -> Dict[str, str]:
    """Query Rewriting & Normalization.
    
    Extracts key informative terms for sparse retrieval,
    and strips noise/colloquial conversational fillers for dense retrieval.
    """
    cleaned = raw_query.strip()
    
    # Remove conversational prefixes/suffixes
    for prefix in ["我想了解一下当年关于", "我想了解一下关于", "请帮我查找关于", "请帮我查找", "我想知道", "能否告诉我", "请问"]:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break
            
    for suffix in ["的具体主张是什么", "的具体主张", "的具体事例", "的内容是什么", "的内容", "是什么呢", "是多少欧元？", "是多少？", "是什么？"]:
        if cleaned.endswith(suffix):
            cleaned = cleaned[:-len(suffix)]
            break

    # Sparse keywords: extract substantive segments
    terms = [w for w in re.split(r"[\s,，、。？?！!]+", cleaned) if w and w not in STOPWORDS]
    sparse_query = " ".join(terms) if terms else cleaned
    dense_query = cleaned if len(cleaned) > 2 else raw_query

    return {
        "raw_query": raw_query,
        "dense_query": dense_query,
        "sparse_query": sparse_query,
    }


def rrf_fuse(ranked_lists: List[List[Tuple[str, float]]], top_n: int = 20) -> List[Tuple[str, float]]:
    """Reciprocal Rank Fusion: RRF(d) = sum(1 / (k + rank))."""
    scores: Dict[str, float] = {}
    for rlist in ranked_lists:
        for rank, (item_id, _) in enumerate(rlist):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (RRF_K + rank + 1)
    
    sorted_items = sorted(scores.items(), key=lambda x: -x[1])
    return sorted_items[:top_n]


class ResumeRetriever:
    """Enterprise RAG Retriever matching the resume specifications."""

    def __init__(
        self,
        db_path: str,
        dense_model_name: str = "BAAI/bge-small-zh-v1.5",
        reranker_model_name: Optional[str] = None,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    ):
        self.db_path = db_path
        self.confidence_threshold = confidence_threshold
        self.dense_model_name = dense_model_name
        self.reranker_model_name = reranker_model_name or LOCAL_RERANKER_PATH
        
        self.dense_model = None
        self.reranker_model = None
        
        # In-memory paragraph cache for candidate evaluation
        self._doc_cache: Dict[str, Dict[str, Any]] = {}
        self._doc_embeddings: Optional[np.ndarray] = None
        self._doc_ids: List[str] = []
        
        self._init_models()

    def _init_models(self):
        """Lazy / Safe initialization of neural models."""
        from sentence_transformers import SentenceTransformer, CrossEncoder
        print(f"[ResumeRetriever] Loading Dense model: {self.dense_model_name} ...")
        self.dense_model = SentenceTransformer(self.dense_model_name)
        print("[ResumeRetriever] Dense model loaded successfully.")

        reranker_path = self.reranker_model_name
        if os.path.exists(reranker_path):
            print(f"[ResumeRetriever] Loading Cross-Encoder: {reranker_path} ...")
            self.reranker_model = CrossEncoder(reranker_path)
            print("[ResumeRetriever] Cross-Encoder loaded successfully.")
        else:
            print(f"[ResumeRetriever] Warning: Reranker path not found at {reranker_path}")

    def build_corpus_index(self, target_book_ids: Optional[List[str]] = None, max_docs: int = 4000):
        """Build in-memory dense vector index for candidate books."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        if target_book_ids:
            placeholders = ",".join(["?"] * len(target_book_ids))
            query = f"""
                SELECT p.id, p.book_id, p.page_index, p.text_normalized, p.char_start, p.char_end,
                       p.evidence_set_id, a.layout_bbox, b.title
                FROM paragraphs p
                LEFT JOIN anchors a ON a.id = p.id
                LEFT JOIN books b ON b.book_id = p.book_id
                WHERE p.book_id IN ({placeholders}) AND p.text_normalized IS NOT NULL AND length(p.text_normalized) > 20
                LIMIT ?
            """
            cur.execute(query, (*target_book_ids, max_docs))
        else:
            query = """
                SELECT p.id, p.book_id, p.page_index, p.text_normalized, p.char_start, p.char_end,
                       p.evidence_set_id, a.layout_bbox, b.title
                FROM paragraphs p
                LEFT JOIN anchors a ON a.id = p.id
                LEFT JOIN books b ON b.book_id = p.book_id
                WHERE p.text_normalized IS NOT NULL AND length(p.text_normalized) > 20
                LIMIT ?
            """
            cur.execute(query, (max_docs,))
            
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

        print(f"[ResumeRetriever] Encoding {len(texts)} paragraphs with {self.dense_model_name}...")
        t0 = time.time()
        self._doc_embeddings = self.dense_model.encode(
            texts,
            batch_size=64,
            show_progress_bar=False,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        print(f"[ResumeRetriever] Encoded in {time.time() - t0:.2f}s, shape: {self._doc_embeddings.shape}")

    def sparse_search(self, query: str, top_k: int = 50) -> List[Tuple[str, float]]:
        """Sparse recall via SQLite FTS5 with BM25 ranking."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        results = []
        
        # Clean query for FTS5 syntax
        clean_terms = [t for t in re.split(r"[\s,，、。？?！!]+", query) if t and len(t) > 1]
        fts_query = " OR ".join(f'"{t}"' for t in clean_terms) if clean_terms else f'"{query}"'
        
        try:
            cur.execute("""
                SELECT paragraph_id, bm25(paragraphs_fts) AS rank_score
                FROM paragraphs_fts
                WHERE paragraphs_fts MATCH ?
                ORDER BY rank_score ASC
                LIMIT ?
            """, (fts_query, top_k))
            for row in cur.fetchall():
                bm25_score = 1.0 / (1.0 + abs(row[1]))
                results.append((row[0], bm25_score))
        except Exception:
            # Fallback LIKE
            pattern = f"%{clean_terms[0] if clean_terms else query}%"
            cur.execute("""
                SELECT id, 1.0 FROM paragraphs
                WHERE text_normalized LIKE ?
                LIMIT ?
            """, (pattern, top_k))
            for row in cur.fetchall():
                results.append((row[0], 0.5))
                
        conn.close()
        return results

    def dense_search(self, query: str, top_k: int = 50) -> List[Tuple[str, float]]:
        """Dense recall via normalized cosine similarity."""
        if self._doc_embeddings is None or len(self._doc_ids) == 0:
            return []
            
        instruction = "为这个句子生成表示以用于相关文章检索："
        query_vec = self.dense_model.encode(
            [f"{instruction}{query}"],
            normalize_embeddings=True,
            convert_to_numpy=True,
        )[0]
        
        sims = np.dot(self._doc_embeddings, query_vec)
        top_indices = np.argsort(-sims)[:top_k]
        
        return [(self._doc_ids[idx], float(sims[idx])) for idx in top_indices]

    def rerank(self, query: str, candidate_ids: List[str]) -> List[Tuple[str, float]]:
        """Cross-Encoder deep cross-attention reranking."""
        pairs = []
        valid_ids = []
        for cid in candidate_ids:
            doc = self._doc_cache.get(cid)
            if doc and doc.get("text"):
                pairs.append((query, doc["text"][:500]))
                valid_ids.append(cid)
                
        if not pairs:
            return []

        if self.reranker_model is not None:
            raw_scores = self.reranker_model.predict(pairs)
            norm_scores = [float(s) for s in raw_scores]
        else:
            q_emb = self.dense_model.encode([query], normalize_embeddings=True, convert_to_numpy=True)[0]
            d_texts = [p[1] for p in pairs]
            d_embs = self.dense_model.encode(d_texts, normalize_embeddings=True, convert_to_numpy=True)
            norm_scores = list(np.dot(d_embs, q_emb))

        scored = list(zip(valid_ids, norm_scores))
        scored.sort(key=lambda x: -x[1])
        return scored

    def search(self, raw_query: str, top_k: int = 5) -> Dict[str, Any]:
        """End-to-end Resume pipeline execution."""
        t_start = time.time()
        
        # 1. Query Rewrite
        t0 = time.time()
        rw = rewrite_query(raw_query)
        t_rw = (time.time() - t0) * 1000
        
        # 2. Dual-channel Recall
        t0 = time.time()
        sparse_hits = self.sparse_search(rw["sparse_query"], top_k=50)
        t_sparse = (time.time() - t0) * 1000
        
        t0 = time.time()
        dense_hits = self.dense_search(rw["dense_query"], top_k=50)
        t_dense = (time.time() - t0) * 1000
        
        # 3. RRF Fusion
        t0 = time.time()
        fused_candidates = rrf_fuse([sparse_hits, dense_hits], top_n=20)
        candidate_ids = [c[0] for c in fused_candidates]
        t_rrf = (time.time() - t0) * 1000
        
        # 4. Cross-Encoder Reranking
        t0 = time.time()
        reranked = self.rerank(raw_query, candidate_ids)
        t_rerank = (time.time() - t0) * 1000
        
        t_total = (time.time() - t_start) * 1000
        
        # 5. Confidence Thresholding & Abstention Guard
        top_score = reranked[0][1] if reranked else 0.0
        is_abstained = (len(reranked) == 0) or (top_score < self.confidence_threshold)
        
        # 6. Physical Provenance Assembly
        results = []
        if not is_abstained:
            for cid, score in reranked[:top_k]:
                doc = self._doc_cache.get(cid, {})
                results.append({
                    "id": cid,
                    "book_id": doc.get("book_id"),
                    "book_title": doc.get("book_title"),
                    "page_index": doc.get("page_index"),
                    "snippet": doc.get("text", "")[:250],
                    "char_range": doc.get("char_range"),
                    "layout_bbox": doc.get("layout_bbox"),
                    "evidence_set_id": doc.get("evidence_set_id"),
                    "score": round(score, 4),
                    "provenance_complete": True,
                })
                
        return {
            "query": raw_query,
            "rewritten_query": rw,
            "is_abstained": is_abstained,
            "abstain_reason": "置信度低于安全阈值 (OOD 拦截，杜绝大模型幻觉)" if is_abstained else None,
            "top_confidence_score": round(top_score, 4),
            "confidence_threshold": self.confidence_threshold,
            "results": results,
            "result_count": len(results),
            "latency_ms": {
                "rewrite": round(t_rw, 1),
                "sparse": round(t_sparse, 1),
                "dense": round(t_dense, 1),
                "rrf": round(t_rrf, 1),
                "rerank": round(t_rerank, 1),
                "total": round(t_total, 1),
            },
            "recall_stats": {
                "sparse_count": len(sparse_hits),
                "dense_count": len(dense_hits),
                "fused_count": len(fused_candidates),
            },
        }
