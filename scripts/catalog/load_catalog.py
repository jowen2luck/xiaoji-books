"""Load Evidence JSONL files into catalog.db (SQLite + FTS5 trigram).

Reads:
    data/evidence/books.jsonl
    data/evidence/pages.jsonl
    data/evidence/paragraphs.jsonl

into catalog.db with full-text search index.

Idempotency:
  - Same evidence_set_id re-load → INSERT OR IGNORE (no-op, no data change).
  - New evidence_set_id → inserts new rows. evidence_sets table tracks which sets loaded.
  - FTS5: inserts are keyed by paragraph_id; re-loading same set is idempotent via INSERT OR IGNORE on paragraphs_fts (FTS5 uses rowid, so we manage by checking existence first).

Usage:
    python scripts/catalog/load_catalog.py --evidence-dir data/evidence --db data/catalog/catalog.db
"""
import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from collections import defaultdict

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from init_db import init_db


def load_jsonl(path: str) -> list:
    """Read JSONL file, return list of records."""
    records = []
    if not os.path.exists(path):
        return records
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"WARN: skipping malformed line in {path}: {e}", file=sys.stderr)
    return records


def get_loaded_evidence_sets(conn) -> set:
    """Return set of evidence_set_ids already loaded."""
    cur = conn.execute("SELECT evidence_set_id FROM evidence_sets")
    return {row[0] for row in cur.fetchall()}


def insert_books(conn, books: list, loaded_sets: set) -> dict:
    """Insert book metadata records. Returns {book_id: evidence_set_id} inserted.
    
    Books table: book_id as PK, first-loaded wins (INSERT OR IGNORE).
    If same book_id appears with new evidence_set, we still track via evidence_sets table.
    """
    sql = """
    INSERT OR IGNORE INTO books
        (book_id, artifact_id, source_path, page_count, ingested_at, evidence_set_id, source_hash)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """
    rows = []
    book_info = {}
    for b in books:
        if b.get("type") != "book_metadata":
            continue
        book_id = b.get("book_id", "")
        es_id = b.get("evidence_set_id", "")
        rows.append((
            book_id,
            b.get("artifact_id", ""),
            b.get("source_path", ""),
            b.get("total_pages", 0),
            b.get("ingested_at", ""),
            es_id,
            b.get("source_hash", ""),
        ))
        book_info[book_id] = es_id
    conn.executemany(sql, rows)
    return book_info


def insert_pages(conn, pages: list, loaded_sets: set) -> dict[str, int]:
    """Insert page-level evidence. Skips pages whose evidence_set_id already loaded.
    
    Returns {evidence_set_id: count} of newly inserted.
    """
    sql = """
    INSERT OR IGNORE INTO pages
        (id, book_id, artifact_id, evidence_set_id, page_index, printed_page,
         text_raw, text_normalized, normalization_version, confidence)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    rows = []
    set_counts: dict[str, int] = defaultdict(int)
    skipped = 0
    for p in pages:
        if p.get("type") not in ("page", "raw_page"):
            continue
        es_id = p.get("evidence_set_id", "")
        # Skip entire evidence set if already loaded
        if es_id and es_id in loaded_sets:
            skipped += 1
            continue
        rows.append((
            p.get("id", ""),
            p.get("book_id", ""),
            p.get("artifact_id", ""),
            es_id,
            p.get("page_index", 0),
            p.get("printed_page", ""),
            p.get("text_raw", ""),
            p.get("text_normalized", ""),
            p.get("normalization_version", ""),
            p.get("confidence", 0.0) or 0.0,
        ))
        set_counts[es_id] += 1
    conn.executemany(sql, rows)
    if skipped:
        print(f"  Pages: skipped {skipped} (already loaded)", file=sys.stderr)
    return dict(set_counts)


def insert_paragraphs(conn, paragraphs: list, loaded_sets: set) -> tuple[dict[str, int], int]:
    """Insert paragraph-level evidence. Skips paragraphs whose evidence_set_id already loaded.
    
    Returns ({evidence_set_id: count}, fts_count) of newly inserted.
    """
    sql_para = """
    INSERT OR IGNORE INTO paragraphs
        (id, book_id, artifact_id, evidence_set_id, page_id, page_index, printed_page,
         text_raw, text_normalized, normalization_version,
         char_start, char_end, confidence)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    # FTS5: delete existing entries for these IDs first (FTS5 doesn't support OR IGNORE)
    # then re-insert. Keyed by paragraph_id as rowid.
    sql_fts_delete = "DELETE FROM paragraphs_fts WHERE paragraph_id = ?"
    sql_fts_insert = """
    INSERT INTO paragraphs_fts (paragraph_id, book_id, page_index, text_normalized)
    VALUES (?, ?, ?, ?)
    """
    para_rows = []
    fts_ops = []  # (delete_id, insert_row)
    set_counts: dict[str, int] = defaultdict(int)
    skipped = 0
    for p in paragraphs:
        if p.get("type") != "paragraph":
            continue
        es_id = p.get("evidence_set_id", "")
        para_id = p.get("id", "")
        char_range = p.get("char_range") or [0, 0]
        # Skip entire evidence set if already loaded
        if es_id and es_id in loaded_sets:
            skipped += 1
            continue
        para_rows.append((
            para_id,
            p.get("book_id", ""),
            p.get("artifact_id", ""),
            es_id,
            p.get("page_id", ""),
            p.get("page_index", 0),
            p.get("printed_page", ""),
            p.get("text_raw", ""),
            p.get("text_normalized", ""),
            p.get("normalization_version", ""),
            char_range[0],
            char_range[1] if len(char_range) > 1 else 0,
            p.get("confidence", 0.0) or 0.0,
        ))
        # For FTS: delete existing same-ID (idempotent re-run), then insert
        fts_ops.append((
            para_id,
            (para_id, p.get("book_id", ""), p.get("page_index", 0), p.get("text_normalized", "")),
        ))
        set_counts[es_id] += 1
    
    conn.executemany(sql_para, para_rows)
    # FTS5: first delete existing rows for these paragraph_ids, then insert
    fts_delete_ids = [(op[0],) for op in fts_ops]
    conn.executemany(sql_fts_delete, fts_delete_ids)
    conn.executemany(sql_fts_insert, [op[1] for op in fts_ops])

    # Defensive dedup: remove residual duplicate rows by keeping lowest rowid per paragraph_id
    conn.execute("""
        DELETE FROM paragraphs_fts WHERE rowid NOT IN (
            SELECT MIN(rowid) FROM paragraphs_fts GROUP BY paragraph_id
        )
    """)

    if skipped:
        print(f"  Paragraphs: skipped {skipped} (already loaded)", file=sys.stderr)
    return dict(set_counts), len(fts_ops)


def insert_anchors(conn, paragraphs: list, loaded_sets: set) -> int:
    """Populate anchors table from paragraph records' char_range + layout_bbox.
    
    Anchors are the Evidence-layer index of physical locations. One anchor per
    paragraph. Uses INSERT OR REPLACE for idempotent re-loading.
    """
    sql_ins = """
    INSERT OR REPLACE INTO anchors
        (id, book_id, artifact_id, page_index, printed_page, block_id,
         char_start, char_end, layout_bbox, extractor_version, evidence_id)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    rows = []
    skipped = 0
    for p in paragraphs:
        if p.get("type") != "paragraph":
            continue
        es_id = p.get("evidence_set_id", "")
        if es_id and es_id in loaded_sets:
            skipped += 1
            continue
        para_id = p.get("id", "")
        char_range = p.get("char_range") or [0, 0]
        bbox_raw = p.get("layout_bbox")
        bbox_str = json.dumps(bbox_raw, ensure_ascii=False) if bbox_raw else None
        rows.append((
            para_id,
            p.get("book_id", ""),
            p.get("artifact_id", ""),
            p.get("page_index", 0),
            p.get("printed_page", ""),
            p.get("block_id", "body"),
            char_range[0],
            char_range[1] if len(char_range) > 1 else 0,
            bbox_str,
            p.get("extractor_version", ""),
            para_id,
        ))
    if rows:
        conn.executemany(sql_ins, rows)
    if skipped:
        print(f"  Anchors: skipped {skipped} (already loaded)", file=sys.stderr)
    return len(rows)


def record_evidence_sets(conn, set_info: dict):
    """Record loaded evidence_sets in tracking table.
    
    set_info: {evidence_set_id: {book_id, artifact_id, extractor_sig, normalization_version, pages, paragraphs}}
    """
    sql = """
    INSERT OR IGNORE INTO evidence_sets
        (evidence_set_id, book_id, artifact_id, extractor_sig, normalization_version,
         page_count, paragraph_count, loaded_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    rows = []
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    for es_id, info in set_info.items():
        rows.append((
            es_id,
            info.get("book_id", ""),
            info.get("artifact_id", ""),
            info.get("extractor_sig", ""),
            info.get("normalization_version", ""),
            info.get("pages", 0),
            info.get("paragraphs", 0),
            now,
        ))
    conn.executemany(sql, rows)


def collect_evidence_set_info(books, pages, paragraphs) -> dict:
    """Aggregate record counts per evidence_set_id from all three files."""
    info: dict[str, dict] = {}
    
    # From books
    for b in books:
        if b.get("type") != "book_metadata":
            continue
        es_id = b.get("evidence_set_id", "")
        if es_id:
            info.setdefault(es_id, {})
            info[es_id]["book_id"] = b.get("book_id", "")
            info[es_id]["artifact_id"] = b.get("artifact_id", "")
            info[es_id]["extractor_sig"] = b.get("extractor", "")
            info[es_id]["normalization_version"] = b.get("normalization_version", "")
    
    # Count pages per set
    page_counts: dict[str, int] = defaultdict(int)
    for p in pages:
        es_id = p.get("evidence_set_id", "")
        if es_id:
            page_counts[es_id] += 1
    for es_id, count in page_counts.items():
        info.setdefault(es_id, {})
        info[es_id]["pages"] = count
    
    # Count paragraphs per set
    para_counts: dict[str, int] = defaultdict(int)
    for p in paragraphs:
        es_id = p.get("evidence_set_id", "")
        if es_id:
            para_counts[es_id] += 1
    for es_id, count in para_counts.items():
        info.setdefault(es_id, {})
        info[es_id]["paragraphs"] = count
    
    return info


def main():
    parser = argparse.ArgumentParser(description="Load evidence JSONL into catalog.db")
    parser.add_argument("--evidence-dir", default="data/evidence",
                        help="Directory containing books.jsonl, pages.jsonl, paragraphs.jsonl")
    parser.add_argument("--db", default="data/catalog/catalog.db")
    parser.add_argument("--force-reset", action="store_true",
                        help="Drop and recreate all catalog data (testing only)")
    args = parser.parse_args()

    # Initialize schema
    conn = sqlite3.connect(args.db)
    
    if args.force_reset:
        # Drop all tables for clean test
        for tbl in ["evidence_sets", "paragraphs_fts", "paragraphs", "pages", "books",
                     "toc_source", "toc_derived", "anchors"]:
            conn.execute(f"DROP TABLE IF EXISTS {tbl}")
        conn.commit()
        print("Force reset: all tables dropped", file=sys.stderr)
    
    conn.close()
    init_db(args.db)
    
    # Load JSONL
    books_path = os.path.join(args.evidence_dir, "books.jsonl")
    pages_path = os.path.join(args.evidence_dir, "pages.jsonl")
    paras_path = os.path.join(args.evidence_dir, "paragraphs.jsonl")
    
    books = load_jsonl(books_path)
    pages = load_jsonl(pages_path)
    paras = load_jsonl(paras_path)
    
    print(f"Loaded: {len(books)} books, {len(pages)} pages, {len(paras)} paragraphs (JSONL)", file=sys.stderr)
    
    # Connect and check what's already loaded
    conn = sqlite3.connect(args.db)
    loaded_sets = get_loaded_evidence_sets(conn)
    if loaded_sets:
        print(f"Already loaded {len(loaded_sets)} evidence set(s): {', '.join(sorted(loaded_sets))}", file=sys.stderr)
    
    # Group records by evidence_set_id to compute what's new
    set_info = collect_evidence_set_info(books, pages, paras)
    new_sets = {es for es in set_info if es not in loaded_sets}
    already_loaded = {es for es in set_info if es in loaded_sets}
    
    if already_loaded:
        print(f"Sets already loaded (will skip): {', '.join(sorted(already_loaded))}", file=sys.stderr)
    if new_sets:
        print(f"New sets to load: {', '.join(sorted(new_sets))}", file=sys.stderr)
    
    # Insert with idempotency (INSERT OR IGNORE + skip loaded sets)
    book_info = insert_books(conn, books, loaded_sets)
    page_set_counts = insert_pages(conn, pages, loaded_sets)
    para_set_counts, fts_count = insert_paragraphs(conn, paras, loaded_sets)
    anchor_count = insert_anchors(conn, paras, loaded_sets)
    
    # Record newly loaded evidence sets
    new_set_info = {es: set_info[es] for es in new_sets}
    record_evidence_sets(conn, new_set_info)
    
    conn.commit()
    
    # Stats
    stats = {}
    for table in ["books", "pages", "paragraphs", "paragraphs_fts", "anchors", "evidence_sets"]:
        cur = conn.execute(f"SELECT COUNT(*) FROM {table}")
        stats[table] = cur.fetchone()[0]
    
    print(f"\nCatalog stats: {stats}")
    total_new_pages = sum(page_set_counts.values())
    total_new_paras = sum(para_set_counts.values())
    print(f"Newly inserted: {total_new_pages} pages, {total_new_paras} paragraphs, {fts_count} FTS entries")
    
    # Quick FTS test
    print("\n=== FTS5 Quick Test ===", file=sys.stderr)
    try:
        cur = conn.execute(
            "SELECT book_id, page_index FROM paragraphs_fts WHERE text_normalized MATCH '马克思' LIMIT 3"
        )
        rows = cur.fetchall()
        if rows:
            print(f"FTS MATCH '马克思': {len(rows)} hit(s)", file=sys.stderr)
        else:
            print("FTS MATCH '马克思': no results", file=sys.stderr)
    except Exception as e:
        print(f"FTS test error: {e}", file=sys.stderr)
    
    conn.close()


if __name__ == "__main__":
    main()
