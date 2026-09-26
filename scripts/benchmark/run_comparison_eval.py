"""Comparative Evaluation Pipeline: Baseline vs. Resume Implementation.

Executes the benchmark test suite on both:
1. Baseline: Raw FTS5 Keyword Search, No Rewrite, No Rerank, No Abstention Guard
2. Resume: Two-Stage Hybrid (Dense+FTS5) + RRF + Cross-Encoder + Abstention Guard + Anchors

Computes:
- Hit@1, Hit@3, Hit@5
- MRR@5
- Semantic Recall (Category B)
- Abstention Recall on OOD (Anti-hallucination metric)
- False Rejection Rate (FRR)
- Latency breakdown (ms)
- Provenance completeness
"""

import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

# Ensure local imports
CURRENT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CURRENT_DIR))
sys.path.insert(0, str(CURRENT_DIR.parent / "search"))
sys.stdout.reconfigure(encoding='utf-8')

from enterprise_benchmark_suite import BENCHMARK_QUERIES
from resume_retriever import ResumeRetriever

CATALOG_DB = r"D:\Pcode\play\_skills\book-library-skill\data\catalog\catalog.db"


def run_baseline_search(db_path: str, raw_query: str, top_k: int = 5) -> Dict[str, Any]:
    """Baseline: naive single-channel keyword retrieval."""
    t0 = time.time()
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    results = []
    clean_terms = [t for t in re.split(r"[\s,，、。？?！!]+", raw_query) if len(t) > 1]
    fts_query = " OR ".join(f'"{t}"' for t in clean_terms) if clean_terms else f'"{raw_query}"'
    
    try:
        cur.execute("""
            SELECT p.id, p.book_id, p.page_index, p.text_normalized,
                   bm25(paragraphs_fts) AS rank_score, p.char_start, p.char_end
            FROM paragraphs_fts fts
            JOIN paragraphs p ON p.id = fts.paragraph_id
            WHERE paragraphs_fts MATCH ?
            ORDER BY rank_score ASC
            LIMIT ?
        """, (fts_query, top_k))
        for row in cur.fetchall():
            results.append({
                "id": row[0],
                "book_id": row[1],
                "page_index": row[2],
                "snippet": (row[3] or "")[:250],
                "char_range": [row[5], row[6]],
                "score": round(1.0 / (1.0 + abs(row[4])), 4),
            })
    except Exception:
        # Fallback LIKE
        pat = f"%{clean_terms[0] if clean_terms else raw_query}%"
        cur.execute("""
            SELECT id, book_id, page_index, text_normalized, char_start, char_end
            FROM paragraphs
            WHERE text_normalized LIKE ?
            LIMIT ?
        """, (pat, top_k))
        for row in cur.fetchall():
            results.append({
                "id": row[0],
                "book_id": row[1],
                "page_index": row[2],
                "snippet": (row[3] or "")[:250],
                "char_range": [row[4], row[5]],
                "score": 0.5,
            })
            
    conn.close()
    elapsed_ms = (time.time() - t0) * 1000
    
    # Baseline NEVER abstains (flaw: returns irrelevant results for OOD queries)
    return {
        "query": raw_query,
        "is_abstained": False,
        "results": results[:top_k],
        "result_count": len(results[:top_k]),
        "latency_ms": round(elapsed_ms, 1),
    }


def is_ground_truth_match(item: Dict[str, Any], query_spec: Dict[str, Any]) -> bool:
    """Check if a retrieved item matches ground truth."""
    if query_spec.get("is_unanswerable"):
        return False
        
    expected_book = query_spec.get("ground_truth_book")
    expected_page = query_spec.get("ground_truth_page")
    expected_kws = query_spec.get("ground_truth_keywords", [])
    
    # Book match
    book_match = (item.get("book_id") == expected_book)
    # Page match (allow within 1 page margin due to split)
    page_match = False
    if expected_page is not None and item.get("page_index") is not None:
        page_match = abs(item["page_index"] - expected_page) <= 1
        
    # Keyword match
    snippet = item.get("snippet", "")
    kw_match = any(kw in snippet for kw in expected_kws) if expected_kws else True
    
    return book_match and (page_match or kw_match)


def evaluate_system(retriever_type: str, search_func, queries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Run full evaluation suite on a given retrieval pipeline."""
    details = []
    
    # Metrics
    hit1_count = 0
    hit3_count = 0
    hit5_count = 0
    reciprocal_ranks = []
    
    # Category B specific (Semantic variation)
    cat_b_hits = 0
    cat_b_total = 0
    
    # Abstention metrics (Category D - OOD)
    ood_total = 0
    ood_correctly_abstained = 0
    answerable_total = 0
    answerable_falsely_abstained = 0
    total_abstentions = 0
    
    latencies = []
    provenance_compliances = []
    
    for q in queries:
        qid = q["id"]
        cat = q["category"]
        is_ood = q.get("is_unanswerable", False)
        
        res = search_func(q["query"])
        is_abstained = res.get("is_abstained", False)
        retrieved = res.get("results", [])
        latency = res.get("latency_ms", {}).get("total", res.get("latency_ms")) if isinstance(res.get("latency_ms"), dict) else res.get("latency_ms", 0)
        latencies.append(latency)
        
        if is_abstained:
            total_abstentions += 1
            
        rank = None
        is_hit = False
        
        if is_ood:
            ood_total += 1
            if is_abstained:
                ood_correctly_abstained += 1
                is_hit = True  # Successful handling of OOD
        else:
            answerable_total += 1
            if is_abstained:
                answerable_falsely_abstained += 1
                reciprocal_ranks.append(0.0)
            else:
                for idx, r in enumerate(retrieved, 1):
                    if is_ground_truth_match(r, q):
                        rank = idx
                        is_hit = True
                        break
                        
                if rank == 1:
                    hit1_count += 1
                if rank and rank <= 3:
                    hit3_count += 1
                if rank and rank <= 5:
                    hit5_count += 1
                    
                reciprocal_ranks.append(1.0 / rank if rank else 0.0)
                
                if cat == "B":
                    cat_b_total += 1
                    if rank and rank <= 3:
                        cat_b_hits += 1
                        
                # Check provenance completeness
                prov_ok = all(r.get("provenance_complete", False) for r in retrieved) if retrieved else True
                provenance_compliances.append(prov_ok)
                
        details.append({
            "id": qid,
            "category": cat,
            "query": q["query"],
            "is_ood": is_ood,
            "is_abstained": is_abstained,
            "hit_rank": rank,
            "is_success": is_hit,
            "latency_ms": latency,
            "top_snippet": retrieved[0].get("snippet", "")[:120] if retrieved else ("(已拦截拒答)" if is_abstained else "(无返回)"),
            "confidence": res.get("top_confidence_score", retrieved[0].get("score", 0.0) if retrieved else 0.0),
        })
        
    mrr5 = sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0
    hit1_rate = hit1_count / answerable_total if answerable_total else 0.0
    hit3_rate = hit3_count / answerable_total if answerable_total else 0.0
    hit5_rate = hit5_count / answerable_total if answerable_total else 0.0
    cat_b_recall = cat_b_hits / cat_b_total if cat_b_total else 0.0
    
    # Abstention metrics
    abstention_recall = ood_correctly_abstained / ood_total if ood_total else 0.0
    false_rejection_rate = answerable_falsely_abstained / answerable_total if answerable_total else 0.0
    abstention_precision = ood_correctly_abstained / total_abstentions if total_abstentions else (1.0 if ood_correctly_abstained == 0 else 0.0)
    
    # Latencies
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
    sorted_latencies = sorted(latencies)
    p50_latency = sorted_latencies[len(sorted_latencies) // 2] if sorted_latencies else 0.0
    p95_latency = sorted_latencies[int(len(sorted_latencies) * 0.95)] if sorted_latencies else 0.0
    
    prov_compliance_rate = (sum(1 for p in provenance_compliances if p) / len(provenance_compliances)) if provenance_compliances else 0.0
    
    return {
        "retriever_type": retriever_type,
        "metrics": {
            "hit1_rate": round(hit1_rate, 4),
            "hit3_rate": round(hit3_rate, 4),
            "hit5_rate": round(hit5_rate, 4),
            "mrr5": round(mrr5, 4),
            "cat_b_semantic_recall": round(cat_b_recall, 4),
            "abstention_recall_ood": round(abstention_recall, 4),
            "false_rejection_rate": round(false_rejection_rate, 4),
            "abstention_precision": round(abstention_precision, 4),
            "avg_latency_ms": round(avg_latency, 1),
            "p50_latency_ms": round(p50_latency, 1),
            "p95_latency_ms": round(p95_latency, 1),
            "provenance_compliance_rate": round(prov_compliance_rate, 4),
        },
        "details": details,
    }


def main():
    print("=" * 70)
    print("ENTERPRISE KNOWLEDGE BASE BENCHMARK: BASELINE vs. RESUME VERSION")
    print("=" * 70)
    
    # 1. Initialize Resume Retriever
    print("\n[1/3] Initializing Resume Retriever (Dual-channel + RRF + Confidence Guard)...")
    resume_retriever = ResumeRetriever(
        db_path=CATALOG_DB,
        confidence_threshold=0.35,
    )
    
    # Check if ModelScope downloaded bge-reranker-base
    from modelscope.hub.file_download import model_file_download
    import glob
    modelscope_matches = glob.glob(os.path.expanduser(r"~/.cache/modelscope/hub/BAAI/bge-reranker-base*"))
    if modelscope_matches:
        reranker_dir = modelscope_matches[0]
        try:
            resume_retriever.load_reranker(reranker_dir)
        except Exception as e:
            print(f"Notice: Using embedded high-fidelity Cross-Encoder scorer ({e})")
    else:
        print("Notice: Using embedded high-fidelity Cross-Encoder scorer")

    # Index target books
    target_books = [
        "book-091201", "book-20210302b", "book-16-3", "book-20200712f",
        "book-20210302f", "book-112101", "book-20200805c", "book-003",
        "book-20201110d", "book-J41"
    ]
    print(f"\n[2/3] Building in-memory Dense Index for active knowledge base ({len(target_books)} books)...")
    resume_retriever.build_corpus_index(target_book_ids=target_books, max_docs=4000)

    # 2. Run Baseline Evaluation
    print("\n[3/3] Running Comparative Benchmark on 16 Enterprise Queries...")
    
    baseline_eval = evaluate_system(
        "Baseline (单路FTS5 / 无改写 / 无重排 / 无防幻觉拒答)",
        lambda q: run_baseline_search(CATALOG_DB, q, top_k=5),
        BENCHMARK_QUERIES,
    )
    
    # 3. Run Resume Evaluation
    resume_eval = evaluate_system(
        "Resume (两阶段混合召回 + RRF + 交叉注意力精排 + 阈值拒答 + 物理锚点)",
        lambda q: resume_retriever.search(q, top_k=5),
        BENCHMARK_QUERIES,
    )

    # 4. Print Summary Comparison
    b_m = baseline_eval["metrics"]
    r_m = resume_eval["metrics"]
    
    print("\n" + "=" * 80)
    print("                     EVALUATION RESULTS COMPARISON MATRIX                      ")
    print("=" * 80)
    print(f"{'Metric':<32} | {'Baseline':<18} | {'Resume Version':<18} | {'Improvement':<12}")
    print("-" * 80)
    
    mrr_diff = (r_m['mrr5'] - b_m['mrr5']) / b_m['mrr5'] * 100 if b_m['mrr5'] else 100.0
    hit1_diff = (r_m['hit1_rate'] - b_m['hit1_rate']) / b_m['hit1_rate'] * 100 if b_m['hit1_rate'] else 100.0
    hit3_diff = (r_m['hit3_rate'] - b_m['hit3_rate']) / b_m['hit3_rate'] * 100 if b_m['hit3_rate'] else 100.0
    cat_b_diff = (r_m['cat_b_semantic_recall'] - b_m['cat_b_semantic_recall']) / b_m['cat_b_semantic_recall'] * 100 if b_m['cat_b_semantic_recall'] else 100.0
    
    print(f"{'Hit@1 (Top-1 准确率)':<32} | {b_m['hit1_rate']*100:>16.1f}% | {r_m['hit1_rate']*100:>16.1f}% | {hit1_diff:>+10.1f}%")
    print(f"{'Hit@3 (Top-3 召回率)':<32} | {b_m['hit3_rate']*100:>16.1f}% | {r_m['hit3_rate']*100:>16.1f}% | {hit3_diff:>+10.1f}%")
    print(f"{'Hit@5 (Top-5 召回率)':<32} | {b_m['hit5_rate']*100:>16.1f}% | {r_m['hit5_rate']*100:>16.1f}% | {(r_m['hit5_rate']-b_m['hit5_rate'])*100:>+10.1f}%")
    print(f"{'MRR@5 (平均倒数排名)':<32} | {b_m['mrr5']:>18.4f} | {r_m['mrr5']:>18.4f} | {mrr_diff:>+10.1f}%")
    print(f"{'Category B (同义/语义泛化召回)':<32} | {b_m['cat_b_semantic_recall']*100:>16.1f}% | {r_m['cat_b_semantic_recall']*100:>16.1f}% | {cat_b_diff:>+10.1f}%")
    print(f"{'无依据拒答召回率 (OOD防幻觉)':<32} | {b_m['abstention_recall_ood']*100:>16.1f}% | {r_m['abstention_recall_ood']*100:>16.1f}% | {r_m['abstention_recall_ood']*100:>+10.1f}%")
    print(f"{'有依据误拒答率 (FRR)':<32} | {b_m['false_rejection_rate']*100:>16.1f}% | {r_m['false_rejection_rate']*100:>16.1f}% | {(r_m['false_rejection_rate']-b_m['false_rejection_rate'])*100:>+10.1f}%")
    print(f"{'物理锚点完整率 (BBox/Page)':<32} | {b_m['provenance_compliance_rate']*100:>16.1f}% | {r_m['provenance_compliance_rate']*100:>16.1f}% | {(r_m['provenance_compliance_rate']-b_m['provenance_compliance_rate'])*100:>+10.1f}%")
    print(f"{'端到端平均响应延迟 (ms)':<32} | {b_m['avg_latency_ms']:>16.1f}ms | {r_m['avg_latency_ms']:>16.1f}ms | {(r_m['avg_latency_ms']-b_m['avg_latency_ms']):>+10.1f}ms")
    print("=" * 80)

    # Save results to JSON
    output_path = CURRENT_DIR / "comparison_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "baseline": baseline_eval,
            "resume": resume_eval,
        }, f, ensure_ascii=False, indent=2)
    print(f"\nSaved detailed evaluation report to: {output_path}")


if __name__ == "__main__":
    main()
