"""Semantic Chunks — build text chunks for embedding/vector index (M4).

Splits paragraph-level Evidence into chunks of target length with overlap.
Each chunk records its parent paragraph IDs so Evidence links are preserved.

Output: JSONL file (data/navigation/semantic_chunks.jsonl)

Schema:
    id: "sc-{chunk_id}"
    book_id: stable ID
    parent_paragraphs: ["para-id-1", ...]
    start_offset: char offset in first parent
    end_offset: char offset in last parent
    chunk_text: text for embedding input
    splitter_v1: "ruler_v1"

Usage:
    python scripts/navigation/semantic_chunks.py --db data/catalog/catalog.db --output data/navigation/semantic_chunks.jsonl
"""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

# Chunking parameters
TARGET_CHUNK_CHARS = 500  # ~500 chars per chunk
MIN_CHUNK_CHARS = 100     # skip tiny chunks
OVERLAP_CHARS = 50        # overlap between chunks


def chunk_text_by_chars(text: str, target: int = TARGET_CHUNK_CHARS,
                        overlap: int = OVERLAP_CHARS) -> list:
    """Split text into chunks by character count with overlap."""
    if len(text) <= target:
        return [(0, len(text), text)] if len(text) >= MIN_CHUNK_CHARS else []
    
    chunks = []
    pos = 0
    while pos < len(text):
        end = min(pos + target, len(text))
        
        # Try to break at sentence boundary (。！？.!?)
        if end < len(text):
            for sep in ["\n\n", "。", "！", "？", ". ", "! ", "? ", "\n", " "]:
                idx = text.rfind(sep, pos + MIN_CHUNK_CHARS, end)
                if idx > pos:
                    end = idx + 1
                    break
        
        chunk_content = text[pos:end].strip()
        if len(chunk_content) >= MIN_CHUNK_CHARS:
            chunks.append((pos, end, chunk_content))
        
        # Advance with overlap
        pos = end - overlap if end < len(text) else end
    
    return chunks


def build_semantic_chunks(db_path: str, output_path: str) -> dict:
    """Build semantic chunks from paragraphs in catalog.db."""
    conn = sqlite3.connect(db_path)
    
    # Get all paragraphs ordered by book and position
    cur = conn.execute("""
        SELECT p.id, p.book_id, p.text_normalized, p.page_index, p.para_index
        FROM paragraphs p
        JOIN books b ON p.book_id = b.book_id
        WHERE p.text_normalized IS NOT NULL AND LENGTH(p.text_normalized) > 20
        ORDER BY p.book_id, p.page_index, p.para_index
    """)
    
    rows = cur.fetchall()
    conn.close()
    
    if not rows:
        print("WARN: No paragraphs found in catalog.db", file=sys.stderr)
        return {"chunks": 0, "books": 0}
    
    # Group paragraphs by book
    book_paragraphs = {}
    for para_id, book_id, text, page_idx, para_idx in rows:
        book_paragraphs.setdefault(book_id, []).append({
            "id": para_id,
            "text": text,
            "page_index": page_idx,
            "para_index": para_idx,
        })
    
    # Generate chunks
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    
    total_chunks = 0
    with open(output_path, "w", encoding="utf-8") as f:
        for book_id, paras in book_paragraphs.items():
            # Combine paragraphs into logical segments
            # Strategy: merge adjacent paragraphs until we hit target chunk size
            buffer_text = ""
            buffer_paras = []
            chunk_idx = 0
            
            for para in paras:
                p_text = para["text"]
                p_id = para["id"]
                
                if len(buffer_text) + len(p_text) > TARGET_CHUNK_CHARS and buffer_text:
                    # Flush buffer as a chunk
                    chunks = chunk_text_by_chars(buffer_text)
                    for start_off, end_off, chunk_content in chunks:
                        chunk_id = f"sc-{book_id}-{chunk_idx:05d}"
                        record = {
                            "id": chunk_id,
                            "book_id": book_id,
                            "parent_paragraphs": [p["id"] for p in buffer_paras],
                            "start_offset": start_off,
                            "end_offset": end_off,
                            "chunk_text": chunk_content,
                            "splitter_v1": "ruler_v1",
                        }
                        f.write(json.dumps(record, ensure_ascii=False) + "\n")
                        chunk_idx += 1
                        total_chunks += 1
                    
                    # Reset buffer
                    buffer_text = ""
                    buffer_paras = []
                
                # Add paragraph to buffer
                if buffer_text:
                    buffer_text += "\n\n" + p_text
                else:
                    buffer_text = p_text
                buffer_paras.append(para)
            
            # Flush remaining
            if buffer_text:
                chunks = chunk_text_by_chars(buffer_text)
                for start_off, end_off, chunk_content in chunks:
                    chunk_id = f"sc-{book_id}-{chunk_idx:05d}"
                    record = {
                        "id": chunk_id,
                        "book_id": book_id,
                        "parent_paragraphs": [p["id"] for p in buffer_paras],
                        "start_offset": start_off,
                        "end_offset": end_off,
                        "chunk_text": chunk_content,
                        "splitter_v1": "ruler_v1",
                    }
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                    chunk_idx += 1
                    total_chunks += 1
    
    return {"chunks": total_chunks, "books": len(book_paragraphs)}


def main():
    parser = argparse.ArgumentParser(description="Build semantic chunks from catalog paragraphs")
    parser.add_argument("--db", default="data/catalog/catalog.db")
    parser.add_argument("--output", default="data/navigation/semantic_chunks.jsonl")
    args = parser.parse_args()
    
    if not Path(args.db).exists():
        print(f"ERROR: {args.db} does not exist.", file=sys.stderr)
        sys.exit(1)
    
    print(f"Building semantic chunks from {args.db}...", file=sys.stderr)
    result = build_semantic_chunks(args.db, args.output)
    
    print(f"Generated {result['chunks']} chunks from {result['books']} books", file=sys.stderr)
    print(f"Output: {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
