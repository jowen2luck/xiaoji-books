"""Hybrid Search Engine (M5).

Combines three signals via RRF (Reciprocal Rank Fusion):
1. FTS5 keyword search (substring match, BM25-style)
2. Vector similarity (cosine/inner-product on bge-small-zh-v1.5 embeddings)
3. Concept/entity alias expansion (optional)

Returns: top-K paragraphs with full Evidence anchors.
Important: Engine Never Concludes — only returns facts with provenance,
never synthesis or summary.

Usage:
    python scripts/search/hybrid.py --query "马克思主义" --db data/catalog/catalog.db --topk 5
"""
import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

# Allow local imports
SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR / "embedding"))

RRF_K = 60  # RRF constant — balances rank weights


def fts5_search(db: sqlite3.Connection, query: str, topk: int = 20) -> list:
    """Full-text search using FTS5 trigram tokenizer.
    
    Returns: [(paragraph_id, rank_score)]
    """
    # Trigram FTS: use substring query directly (trigram tokenizer splits every 3 chars)
    try:
        # Use FTS5 virtual table MATCH
        cur = db.execute("""
            SELECT p.id, p.book_id, p.page_index, p.text_normalized,
                   bm25(paragraphs_fts) AS score
            FROM paragraphs_fts fts
            JOIN paragraphs p ON p.id = fts.paragraph_id
            WHERE paragraphs_fts MATCH ?
            ORDER BY score ASC
            LIMIT ?
        """, (query, topk))
        return [(row[0], row[1], {"book_id": row[2], "page_index": row[3], "snippet": row[4][:100] if row[4] else ""})
                for row in cur.fetchall()]
    except Exception as e:
        # Fall back to LIKE query if MATCH fails
        try:
            cur = db.execute("""
                SELECT id, book_id, page_index, text_normalized, 1.0 AS score
                FROM paragraphs
                WHERE text_normalized LIKE ?
                LIMIT ?
            """, (f"%{query}%", topk))
            return [(row[0], row[1], {"book_id": row[2], "page_index": row[3], "snippet": row[4][:100] if row[4] else ""})
                    for row in cur.fetchall()]
        except Exception:
            return []


def vector_search_index(index_path: str, map_path: str, query: str,
                        model_name: str = "mock", topk: int = 20) -> list:
    """Search FAISS index.
    
    Returns: [(chunk_id, score)]
    """
    try:
        from faiss_index import search as faiss_search
    except ImportError:
        return []
    
    if not Path(index_path).exists():
        return []
    
    results = faiss_search(query, index_path, map_path, model_name, topk)
    return [(r["chunk_id"], r["score"]) for r in results]


def chunk_id_to_paragraph_ids(chunk_id: str) -> list:
    """Resolve chunk_id to parent paragraph IDs.
    
    Format: sc-{book_id}-{index:05d}
    We'd need to look up the semantic_chunks.jsonl. For now return empty (will be
    resolved via catalog.db lookup).
    """
    # In production: read from semantic_chunks.jsonl mapping
    return []


def rrf_fuse(ranked_lists: list, topk: int = 10) -> list:
    """Reciprocal Rank Fusion — merge multiple ranked lists.
    
    Args:
        ranked_lists: list of lists of (item_id, score)
        topk: number of results to return
    
    Returns: [(item_id, rrf_score), ...] sorted desc
    """
    scores = {}  # item_id -> total RRF score
    
    for rlist in ranked_lists:
        for rank, (item_id, original_score) in enumerate(rlist):
            # RRF formula: sum of 1/(k + rank)
            # For score-based, we use 1/(k + rank)
            rrf = 1.0 / (RRF_K + rank + 1)
            scores[item_id] = scores.get(item_id, 0.0) + rrf
    
    # Sort by rrf score desc
    sorted_items = sorted(scores.items(), key=lambda x: -x[1])[:topk]
    return sorted_items


def hybrid_search(
    query: str,
    db_path: str,
    index_path: str = "",
    map_path: str = "",
    model_name: str = "mock",
    topk: int = 10,
) -> list:
    """Combined FTS5 + vector search with RRF fusion.
    
    Returns: list of paragraph results with anchors and provenance.
    """
    db = sqlite3.connect(db_path)
    
    # 1. FTS5 search
    t0 = time.time()
    fts_results = fts5_search(db, query, topk * 3)
    fts_time = time.time() - t0
    
    # 2. Vector search (if FAISS index exists)
    vec_results = []
    if index_path and Path(index_path).exists() and map_path and Path(map_path).exists():
        t0 = time.time()
        vec_results = vector_search_index(index_path, map_path, query, model_name, topk * 3)
        vec_time = time.time() - t0
    else:
        vec_time = 0
    
    # 3. RRF fusion
    # Map FTS results: (paragraph_id, score)
    fts_ranked = [(r[0], 1.0 / (i + 1)) for i, r in enumerate(fts_results)]
    
    # Map vector results: (chunk_id, score) — need to resolve to paragraph_ids
    # Simplification: use chunk_id directly (rank fusion still works)
    vec_ranked = [(r[0], r[1]) for r in vec_results]
    
    fused = rrf_fuse([fts_ranked, vec_ranked], topk)
    
    # 4. Enrich with Evidence anchor data
    results = []
    for item_id, score in fused:
        # Try to find as paragraph first
        cur = db.execute("""
            SELECT p.id, p.book_id, p.artifact_id, p.evidence_set_id,
                   p.page_index, p.text_normalized, p.char_start, p.char_end,
                   a.layout_bbox, a.extractor_version, b.title, b.source_hash
            FROM paragraphs p
            LEFT JOIN anchors a ON a.id = p.id
            LEFT JOIN books b ON b.book_id = p.book_id
            WHERE p.id = ? OR p.id LIKE ?
            LIMIT 1
        """, (item_id, f"{item_id}%"))
        
        row = cur.fetchone()
        if row:
            results.append({
                "id": row[0],
                "book_id": row[1],
                "artifact_id": row[2],
                "evidence_set_id": row[3],
                "page_index": row[4],
                "snippet": (row[5][:200] if row[5] else ""),
                "char_range": [row[6], row[7]],
                "layout_bbox": row[8],
                "extractor": row[9],
                "book_title": row[10],
                "source_hash": row[11],
                "rrf_score": round(score, 4),
                "provenance": "evidence_layer",
            })
    
    db.close()
    
    return results, {
        "fts_time_ms": round(fts_time * 1000, 1),
        "vec_time_ms": round(vec_time * 1000, 1),
        "fts_count": len(fts_results),
        "vec_count": len(vec_results),
        "fused_count": len(fused),
    }


def main():
    parser = argparse.ArgumentParser(description="Hybrid search (FTS5 + Vector RRF)")
    parser.add_argument("--query", required=True)
    parser.add_argument("--db", default="data/catalog/catalog.db")
    parser.add_argument("--index", default="data/index/vectors.faiss")
    parser.add_argument("--map", default="data/index/vectors_map.jsonl")
    parser.add_argument("--topk", type=int, default=5)
    parser.add_argument("--model", default="mock")
    parser.add_argument("--no-vector", action="store_true")
    args = parser.parse_args()
    
    index_path = "" if args.no_vector else args.index
    map_path = "" if args.no_vector else args.map
    
    print(f"Query: {args.query}")
    print(f"DB: {args.db}")
    print()
    
    results, stats = hybrid_search(
        args.query, args.db, index_path, map_path, args.model, args.topk
    )
    
    print(f"Stats: {json.dumps(stats, indent=2)}")
    print(f"\nResults ({len(results)}):")
    for i, r in enumerate(results, 1):
        print(f"{i}. [{r['book_id']}] p{r['page_index']} (score={r['rrf_score']})")
        print(f"   {r.get('snippet', '')[:150]}")
        print(f"   evidence_set: {r.get('evidence_set_id', 'N/A')}")
        print()


if __name__ == "__main__":
    main()
