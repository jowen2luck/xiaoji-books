#!/usr/bin/env python3
"""
Initialize catalog.db with schema (single SQLite file per decision A).
"""

import sqlite3
import os
import sys

SCHEMA_SQL = """
-- 书目
CREATE TABLE IF NOT EXISTS books (
    book_id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL,
    source_path TEXT,
    title TEXT,
    authors TEXT,
    language TEXT,
    page_count INTEGER,
    status TEXT,
    ingested_at TEXT,
    evidence_set_id TEXT,
    source_hash TEXT
);

-- 页面 (id 包含 evidence_set_id 作为不可变边界)
CREATE TABLE IF NOT EXISTS pages (
    id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL,
    artifact_id TEXT,
    evidence_set_id TEXT,
    page_index INTEGER,
    printed_page TEXT,
    text_raw TEXT,
    text_normalized TEXT,
    normalization_version TEXT,
    confidence REAL,
    char_count INTEGER,
    FOREIGN KEY (book_id) REFERENCES books(book_id)
);

-- 段落 (id 包含 evidence_set_id 作为不可变边界)
CREATE TABLE IF NOT EXISTS paragraphs (
    id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL,
    artifact_id TEXT,
    evidence_set_id TEXT,
    page_id TEXT,
    page_index INTEGER,
    printed_page TEXT,
    para_index INTEGER,
    text_raw TEXT,
    text_normalized TEXT,
    normalization_version TEXT,
    char_start INTEGER,
    char_end INTEGER,
    confidence REAL,
    FOREIGN KEY (book_id) REFERENCES books(book_id),
    FOREIGN KEY (page_id) REFERENCES pages(id)
);

-- Evidence Set 追踪 (幂等性保障)
CREATE TABLE IF NOT EXISTS evidence_sets (
    evidence_set_id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL,
    artifact_id TEXT,
    extractor_sig TEXT,
    normalization_version TEXT,
    page_count INTEGER,
    paragraph_count INTEGER,
    loaded_at TEXT,
    FOREIGN KEY (book_id) REFERENCES books(book_id)
);

-- 原始目录 (source_toc)
CREATE TABLE IF NOT EXISTS toc_source (
    id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL,
    page_index INTEGER,
    printed_page TEXT,
    title TEXT,
    level INTEGER,
    parent_id TEXT,
    FOREIGN KEY (book_id) REFERENCES books(book_id)
);

-- 派生目录 (derived_catalog)
CREATE TABLE IF NOT EXISTS toc_derived (
    id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL,
    page_index INTEGER,
    printed_page TEXT,
    title TEXT,
    level INTEGER,
    parent_id TEXT,
    confidence REAL NOT NULL,
    provenance TEXT,
    FOREIGN KEY (book_id) REFERENCES books(book_id)
);

-- Anchor 索引
CREATE TABLE IF NOT EXISTS anchors (
    id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    page_index INTEGER,
    printed_page TEXT,
    block_id TEXT,
    char_start INTEGER,
    char_end INTEGER,
    layout_bbox TEXT,
    extractor_version TEXT,
    evidence_id TEXT,
    FOREIGN KEY (book_id) REFERENCES books(book_id)
);

-- FTS5 全文索引 (standalone, trigram tokenizer 支持 CJK 子串匹配)
CREATE VIRTUAL TABLE IF NOT EXISTS paragraphs_fts USING fts5(
    text_normalized,
    paragraph_id UNINDEXED,
    book_id UNINDEXED,
    page_index UNINDEXED,
    tokenize='trigram'
);

CREATE INDEX IF NOT EXISTS idx_pages_book ON pages(book_id);
CREATE INDEX IF NOT EXISTS idx_paragraphs_book ON paragraphs(book_id);
CREATE INDEX IF NOT EXISTS idx_anchors_book ON anchors(book_id);
CREATE INDEX IF NOT EXISTS idx_pages_page_idx ON pages(page_index);
CREATE INDEX IF NOT EXISTS idx_paragraphs_page_idx ON paragraphs(page_index);
CREATE INDEX IF NOT EXISTS idx_pages_evidence_set ON pages(evidence_set_id);
CREATE INDEX IF NOT EXISTS idx_paragraphs_evidence_set ON paragraphs(evidence_set_id);
CREATE INDEX IF NOT EXISTS idx_evidence_sets_book ON evidence_sets(book_id);
"""


def init_db(db_path: str):
    """Create catalog.db with schema."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    if os.path.exists(db_path):
        print(f"WARNING: {db_path} already exists, will use existing file")
    
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    
    # Verify
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    print(f"Initialized catalog.db at {db_path}")
    print(f"Tables: {', '.join(sorted(tables))}")
    return db_path


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Initialize catalog.db")
    parser.add_argument("--db", default="data/catalog/catalog.db",
                        help="Path to catalog.db")
    args = parser.parse_args()
    
    init_db(args.db)


if __name__ == "__main__":
    main()
