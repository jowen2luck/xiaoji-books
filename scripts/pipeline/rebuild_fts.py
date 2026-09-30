#!/usr/bin/env python3
"""
Rebuild FTS5 trigram index from navigation paragraphs_v2.jsonl files.

Reads:  data/evidence/navigation/<book_id>/paragraphs_v2.jsonl
Writes: data/catalog/catalog.db paragraphs_fts (dropped and recreated)

Usage:
  python scripts/pipeline/rebuild_fts.py
"""

import json
import os
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

NAV_DIR = PROJECT_ROOT / "data" / "evidence" / "navigation"
DB_PATH = PROJECT_ROOT / "data" / "catalog" / "catalog.db"


def normalizer():
    """Lazy import normalizer to avoid circular deps."""
    from scripts.pipeline.normalizer import normalize_text
    return normalize_text


def rebuild():
    if not NAV_DIR.exists():
        print(f"Navigation directory not found: {NAV_DIR}", file=sys.stderr)
        return

    # Find all paragraphs_v2.jsonl files
    para_files = list(NAV_DIR.glob("*/paragraphs_v2.jsonl"))
    if not para_files:
        print("No paragraphs_v2.jsonl files found", file=sys.stderr)
        return

    print(f"Found {len(para_files)} book paragraph files", file=sys.stderr)

    # Connect to catalog.db
    os.makedirs(DB_PATH.parent, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))

    # Drop and recreate FTS5 table
    print("Dropping old paragraphs_fts...", file=sys.stderr)
    conn.execute("DROP TABLE IF EXISTS paragraphs_fts")
    conn.execute("""
        CREATE VIRTUAL TABLE paragraphs_fts USING fts5(
            text_normalized,
            paragraph_id UNINDEXED,
            book_id UNINDEXED,
            page_index UNINDEXED,
            tokenize='trigram'
        )
    """)
    print("Created new paragraphs_fts table", file=sys.stderr)

    # Import normalization
    norm_fn = normalizer()

    # Insert paragraphs
    total = 0
    batch = []
    BATCH_SIZE = 5000

    for para_file in sorted(para_files):
        book_id = para_file.parent.name
        with open(para_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                para = json.loads(line)

                raw_text = para.get("text", "")
                if not raw_text.strip():
                    continue

                # Apply normalization
                norm_text, _, _ = norm_fn(raw_text)

                batch.append((
                    norm_text,
                    para.get("id", ""),
                    book_id,
                    para.get("page_index", 0),
                ))

                if len(batch) >= BATCH_SIZE:
                    conn.executemany(
                        "INSERT INTO paragraphs_fts (text_normalized, paragraph_id, book_id, page_index) VALUES (?, ?, ?, ?)",
                        batch,
                    )
                    total += len(batch)
                    batch = []
                    print(f"  inserted {total} rows...", file=sys.stderr)

    # Final batch
    if batch:
        conn.executemany(
            "INSERT INTO paragraphs_fts (text_normalized, paragraph_id, book_id, page_index) VALUES (?, ?, ?, ?)",
            batch,
        )
        total += len(batch)

    conn.commit()

    # Verify
    cnt = conn.execute("SELECT COUNT(*) FROM paragraphs_fts").fetchone()[0]
    print(f"\nDone. Inserted {total} rows. paragraphs_fts now has {cnt} rows.", file=sys.stderr)

    # Quick sanity check
    cur = conn.execute(
        "SELECT book_id, substr(text_normalized, 1, 60) FROM paragraphs_fts LIMIT 3"
    )
    print("\nSample:", file=sys.stderr)
    for row in cur:
        print(f"  {row[0]}: {row[1]}", file=sys.stderr)

    # Test trigram search
    print("\n=== Trigram search test ===", file=sys.stderr)
    for query in ["喀琅施塔得", "列宁", "斯大林"]:
        try:
            cur = conn.execute(
                "SELECT book_id, substr(text_normalized, 1, 60) FROM paragraphs_fts WHERE paragraphs_fts MATCH ? LIMIT 3",
                (query,)
            )
            results = cur.fetchall()
            print(f"  '{query}': {len(results)} results", file=sys.stderr)
        except Exception as e:
            print(f"  '{query}': ERROR {e}", file=sys.stderr)

    conn.close()


if __name__ == "__main__":
    rebuild()
