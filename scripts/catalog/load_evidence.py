#!/usr/bin/env python3
"""
Load evidence JSONL files into catalog.db.
"""

import json
import sqlite3
import os
import argparse
from pathlib import Path


def load_evidence_to_db(evidence_dir: str, db_path: str):
    """Load evidence JSONL into SQLite."""
    evidence_path = Path(evidence_dir)
    
    conn = sqlite3.connect(db_path)
    
    # Load books
    books_path = evidence_path / "books.jsonl"
    if books_path.exists():
        with open(books_path, "r", encoding="utf-8") as f:
            for line in f:
                b = json.loads(line.strip())
                conn.execute("""
                    INSERT OR REPLACE INTO books 
                    (book_id, artifact_id, source_path, page_count, 
                     ingested_at, evidence_set_id, source_hash, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    b.get("book_id"),
                    b.get("artifact_id"),
                    b.get("source_path"),
                    b.get("total_pages"),
                    b.get("ingested_at"),
                    b.get("evidence_set_id"),
                    b.get("source_hash"),
                    "ingested",
                ))
        conn.commit()
        print(f"Loaded books from {books_path}")
    
    # Load pages
    pages_path = evidence_path / "pages.jsonl"
    if pages_path.exists():
        count = 0
        with open(pages_path, "r", encoding="utf-8") as f:
            for line in f:
                p = json.loads(line.strip())
                conn.execute("""
                    INSERT OR REPLACE INTO pages
                    (id, book_id, page_index, text_raw, text_normalized,
                     normalization_version, char_count, artifact_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    p.get("id"),
                    p.get("book_id"),
                    p.get("page_index"),
                    p.get("text_raw"),
                    p.get("text_normalized"),
                    p.get("normalization_version"),
                    p.get("char_count"),
                    p.get("artifact_id"),
                ))
                count += 1
        conn.commit()
        print(f"Loaded {count} pages from {pages_path}")
    
    # Load paragraphs
    paras_path = evidence_path / "paragraphs.jsonl"
    if paras_path.exists():
        count = 0
        with open(paras_path, "r", encoding="utf-8") as f:
            for line in f:
                p = json.loads(line.strip())
                conn.execute("""
                    INSERT OR REPLACE INTO paragraphs
                    (id, book_id, page_id, page_index, para_index,
                     text_raw, text_normalized, normalization_version, char_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    p.get("id"),
                    p.get("book_id"),
                    p.get("page_id"),
                    p.get("page_index"),
                    p.get("para_index"),
                    p.get("text_raw"),
                    p.get("text_normalized"),
                    p.get("normalization_version"),
                    p.get("char_count"),
                ))
                count += 1
        conn.commit()
        print(f"Loaded {count} paragraphs from {paras_path}")
    
    # Build FTS5 index
    print("Building FTS5 index...")
    conn.execute("DELETE FROM paragraphs_fts")
    conn.execute("""
        INSERT INTO paragraphs_fts(paragraph_id, book_id, page_index, text_normalized)
        SELECT id, book_id, page_index, text_normalized FROM paragraphs
    """)
    conn.commit()
    
    # Verify
    count = conn.execute("SELECT COUNT(*) FROM paragraphs_fts").fetchone()[0]
    print(f"FTS5 index: {count} rows")
    
    conn.close()
    print("Done!")


def main():
    parser = argparse.ArgumentParser(description="Load evidence into catalog.db")
    parser.add_argument("--evidence", default="data/evidence/")
    parser.add_argument("--db", default="data/catalog/catalog.db")
    args = parser.parse_args()
    
    load_evidence_to_db(args.evidence, args.db)


if __name__ == "__main__":
    main()
