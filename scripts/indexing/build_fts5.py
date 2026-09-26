#!/usr/bin/env python3
"""FTS5 Index Builder — incremental, relies on Evidence JSONL files."""

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path


def make_parser():
    parser = argparse.ArgumentParser(description="FTS5 builder (incremental, multi-dir)")
    parser.add_argument("--evidence-dir", default="data/evidence",
                       help="Primary evidence dir (also scans shard* subdirs)")
    parser.add_argument("--db", default="data/catalog/fts5.db")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--scan-dirs", nargs="*", default=[],
                       help="Additional evidence directories to scan (e.g. data/evidence/shard1)")
    return parser


def init_db(conn, rebuild=False):
    if rebuild:
        for t in ["pages_fts", "pages_meta", "books_meta"]:
            conn.execute(f"DROP TABLE IF EXISTS {t}")
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
            book_id UNINDEXED,
            page_index UNINDEXED,
            evidence_set_id UNINDEXED,
            text_normalized,
            tokenize = 'trigram'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pages_meta (
            id TEXT PRIMARY KEY,
            book_id TEXT NOT NULL,
            page_index INTEGER NOT NULL,
            evidence_set_id TEXT,
            confidence REAL,
            block_count INTEGER,
            extractor TEXT,
            ingested_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS books_meta (
            book_id TEXT PRIMARY KEY,
            total_pages INTEGER,
            processed_pages INTEGER,
            source_path TEXT,
            evidence_set_id TEXT,
            ingested_at TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pm_book ON pages_meta(book_id)")
    conn.commit()


def build_index(ev_dir, db_path, rebuild=False):
    pages_file = Path(ev_dir) / "pages.jsonl"
    books_file = Path(ev_dir) / "books.jsonl"
    if not pages_file.exists():
        print(f"[FTS5] ERROR: {pages_file} not found", file=sys.stderr)
        return 0, 0

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if rebuild and db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(str(db_path))
    init_db(conn, rebuild)

    existing = set()
    if not rebuild:
        try:
            existing = set(r[0] for r in conn.execute("SELECT id FROM pages_meta"))
        except Exception:
            existing = set()
        print(f"[FTS5] Incremental: {len(existing)} pages already indexed", file=sys.stderr)

    books_meta = {}
    if books_file.exists():
        for line in open(books_file, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                if r.get("type") == "book_metadata":
                    books_meta[r["book_id"]] = r
            except json.JSONDecodeError:
                pass

    total = new = 0
    start = time.time()

    with conn:
        for line in open(pages_file, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue

            pid = r.get("id")
            if not pid or pid in existing:
                total += 1
                continue

            text = r.get("text_normalized", "")
            if not text.strip():
                total += 1
                continue

            conn.execute(
                "INSERT INTO pages_fts (book_id, page_index, evidence_set_id, text_normalized) VALUES (?, ?, ?, ?)",
                (r.get("book_id", ""), r.get("page_index", 0), r.get("evidence_set_id", ""), text)
            )
            conn.execute(
                "INSERT OR REPLACE INTO pages_meta (id, book_id, page_index, evidence_set_id, confidence, block_count, extractor, ingested_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (pid, r.get("book_id", ""), r.get("page_index", 0), r.get("evidence_set_id", ""),
                 r.get("confidence", 0.0), r.get("block_count", 0),
                 r.get("extractor", ""), r.get("ingested_at", ""))
            )
            new += 1
            total += 1

        for bid, meta in books_meta.items():
            conn.execute(
                "INSERT OR REPLACE INTO books_meta (book_id, total_pages, processed_pages, source_path, evidence_set_id, ingested_at) VALUES (?, ?, ?, ?, ?, ?)",
                (bid, meta.get("total_pages", 0), meta.get("processed_pages", 0),
                 meta.get("source_path", ""), meta.get("evidence_set_id", ""),
                 meta.get("ingested_at", ""))
            )

    elapsed = time.time() - start
    cnt = conn.execute("SELECT COUNT(*) FROM pages_fts").fetchone()[0]
    bc = conn.execute("SELECT COUNT(DISTINCT book_id) FROM pages_fts").fetchone()[0]

    print(f"[FTS5] Indexed {new} new / {total} total pages", file=sys.stderr)
    print(f"[FTS5] DB rows: {cnt}, books: {bc}, time: {elapsed:.1f}s", file=sys.stderr)

    conn.close()
    return cnt, bc


def main():
    args = make_parser().parse_args()

    # Auto-detect shard* subdirectories under evidence-dir
    ev_primary = Path(args.evidence_dir)
    shard_dirs = []
    if ev_primary.exists():
        for child in sorted(ev_primary.iterdir()):
            if child.is_dir() and child.name.startswith("shard") and (child / "pages.jsonl").exists():
                shard_dirs.append(str(child))

    all_dirs = [args.evidence_dir] + args.scan_dirs + shard_dirs
    all_dirs = list(dict.fromkeys(all_dirs))  # dedupe, preserve order

    total_cnt = 0
    total_bc = 0
    for d in all_dirs:
        print(f"[FTS5] Scanning: {d}", file=sys.stderr)
        cnt, bc = build_index(d, args.db, args.rebuild)
        total_cnt = cnt  # build_index returns cumulative total
        total_bc = bc

    print(json.dumps({"status": "ok", "pages_indexed": int(total_cnt), "books": int(total_bc), "dirs_scanned": len(all_dirs)}))


if __name__ == "__main__":
    main()
