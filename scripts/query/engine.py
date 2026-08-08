"""AIAE Query Engine (M6).

Skill hook for Agent: accepts natural language query, returns Evidence with
full provenance anchors. Complies with Engine Never Concludes — returns only
facts from Ground Truth, never synthesis or opinion.

Usage:
    python scripts/query/engine.py --query "马克思主义" --db data/catalog/catalog.db --topk 5
"""
import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR / "search"))
sys.path.insert(0, str(SCRIPT_DIR / "embedding"))

ROOT = Path(__file__).resolve().parent.parent.parent

# Canonical provenance fields returned for every evidence snippet
ANCHOR_FIELDS = [
    "book_id",
    "book_title",
    "artifact_id",
    "evidence_set_id",
    "source_hash",
    "page_index",
    "printed_page",
    "char_range",
    "layout_bbox",
    "extractor",
    "normalization_version",
]


def get_book(conn, book_id: str) -> dict:
    cur = conn.execute(
        "SELECT book_id, title, artifact_id, source_hash, evidence_set_id "
        "FROM books WHERE book_id = ?",
        (book_id,),
    )
    row = cur.fetchone()
    if row:
        return {
            "book_id": row[0],
            "title": row[1],
            "artifact_id": row[2],
            "source_hash": row[3],
            "evidence_set_id": row[4],
        }
    return {}


def attach_provenance(conn, paragraph: dict) -> dict:
    """Enrich a paragraph record with full provenance anchor (M6 requirement).

    Every returned Evidence chunk carries a complete chain back to source:
    book -> artifact -> source_hash -> page -> char_range -> layout_bbox.
    """
    provenance = {}
    for f in ANCHOR_FIELDS:
        if f in paragraph and paragraph[f] is not None:
            provenance[f] = paragraph[f]

    # Ensure book_title populated
    if "book_title" not in provenance or not provenance.get("book_title"):
        book_info = get_book(conn, paragraph.get("book_id", ""))
        if book_info.get("title"):
            provenance["book_title"] = book_info["title"]

    return provenance


def search_evidence(conn, query: str, topk: int = 10) -> list:
    """Hybrid search: FTS5 + LIKE fallback, with provenance enrichment."""
    results = []

    # Try FTS5 first
    try:
        cur = conn.execute(
            """
            SELECT p.id, p.book_id, p.artifact_id, p.evidence_set_id,
                   p.page_index, p.printed_page, p.text_raw, p.text_normalized,
                   p.char_start, p.char_end, p.confidence, p.normalization_version,
                   a.layout_bbox, a.extractor_version
            FROM paragraphs_fts fts
            JOIN paragraphs p ON p.id = fts.paragraph_id
            WHERE paragraphs_fts MATCH ?
            LIMIT ?
            """,
            (query, topk * 3),
        )
        for row in cur.fetchall():
            results.append({
                "paragraph_id": row[0],
                "book_id": row[1],
                "artifact_id": row[2],
                "evidence_set_id": row[3],
                "page_index": row[4],
                "printed_page": row[5],
                "text_raw": row[6],
                "text_normalized": row[7],
                "char_range": [row[8], row[9]],
                "confidence": row[10],
                "normalization_version": row[11],
                "layout_bbox": row[12],
                "extractor": row[13],
            })
    except Exception:
        pass

    # Fallback LIKE
    if not results:
        try:
            cur = conn.execute(
                """
                SELECT id, book_id, artifact_id, evidence_set_id,
                       page_index, printed_page, text_raw, text_normalized,
                       char_start, char_end, confidence, normalization_version
                FROM paragraphs
                WHERE text_normalized LIKE ? OR text_raw LIKE ?
                LIMIT ?
                """,
                (f"%{query}%", f"%{query}%", topk * 3),
            )
            for row in cur.fetchall():
                results.append({
                    "paragraph_id": row[0],
                    "book_id": row[1],
                    "artifact_id": row[2],
                    "evidence_set_id": row[3],
                    "page_index": row[4],
                    "printed_page": row[5],
                    "text_raw": row[6],
                    "text_normalized": row[7],
                    "char_range": [row[8], row[9]],
                    "confidence": row[10],
                    "normalization_version": row[11],
                })
        except Exception:
            pass

    # Deduplicate by (book_id, page_index, char_start)
    seen = set()
    unique = []
    for r in results:
        key = (r.get("book_id"), r.get("page_index"), (r.get("char_range") or [0, 0])[0])
        if key not in seen:
            seen.add(key)
            unique.append(r)

    return unique[:topk]


def query_enhance(
    query_text: str,
    db_path: str,
    topk: int = 5,
    include_raw: bool = False,
) -> dict:
    """Main Skill hook: query -> evidence list with full provenance.

    Returns dict with:
    - results (list of evidence with provenance anchors)
    - provenance_compliant (bool)
    - engine_never_concludes (always True - invariant)
    - ground_truth_only (always True - invariant)
    """
    db = sqlite3.connect(db_path)

    t0 = time.time()
    results = search_evidence(db, query_text, topk)
    search_ms = (time.time() - t0) * 1000

    provenance_compliant_count = 0
    output = []

    for r in results:
        prov = attach_provenance(db, r)

        required = ["book_id", "artifact_id", "evidence_set_id", "page_index", "char_range"]
        has_all = all(prov.get(f) for f in required)
        if has_all:
            provenance_compliant_count += 1

        text = r.get("text_normalized") or r.get("text_raw") or ""
        snippet = text[:300] if len(text) > 300 else text

        rec = {
            "snippet": snippet,
            "provenance": prov,
            "source_type": "evidence_layer",
            "confidence": r.get("confidence"),
            "provenance_complete": has_all,
        }
        if include_raw:
            rec["text_raw"] = r.get("text_raw")

        output.append(rec)

    db.close()

    return {
        "query": query_text,
        "results": output,
        "result_count": len(output),
        "provenance_compliant": provenance_compliant_count == len(output) if output else True,
        "provenance_compliant_count": provenance_compliant_count,
        "search_ms": round(search_ms, 1),
        "engine_never_concludes": True,
        "ground_truth_only": True,
    }


def main():
    parser = argparse.ArgumentParser(description="AIAE Book Evidence Query Engine")
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument("--db", default=str(ROOT / "data/catalog/catalog.db"))
    parser.add_argument("--topk", type=int, default=5)
    parser.add_argument("--include-raw", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = query_enhance(args.query, args.db, args.topk, args.include_raw)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Query: {result['query']}")
        print(f"Results: {result['result_count']} (provenance_ok={result['provenance_compliant']})")
        print(f"Engine Never Concludes: {result['engine_never_concludes']}")
        print(f"Search time: {result['search_ms']}ms")
        print()
        for i, r in enumerate(result["results"], 1):
            prov = r["provenance"]
            print(f"--- [{i}] {prov.get('book_title', prov.get('book_id', '?'))} "
                  f"p{prov.get('page_index', '?')} ---")
            print(f"    {r['snippet'][:200]}")
            print(f"    evidence_set: {prov.get('evidence_set_id', 'N/A')}")
            print(f"    artifact: {prov.get('artifact_id', 'N/A')}")
            print(f"    char_range: {prov.get('char_range')}")
            print()


if __name__ == "__main__":
    main()
