#!/usr/bin/env python3
"""Quality & Coverage Spot Check Tool for Distributed Book Pipeline.

Audits:
1. Total pages vs pages with meaningful text
2. Empty pages (scanned images without text layer) vs extractable pages
3. Random text samples from extracted books
"""
import json
import random
from pathlib import Path


def audit_shard(shard_dir: Path):
    if not shard_dir.exists():
        return
    pages_file = shard_dir / "pages.jsonl"
    books_file = shard_dir / "books.jsonl"
    if not pages_file.exists():
        return

    books = []
    if books_file.exists():
        with open(books_file, encoding="utf-8") as f:
            books = [json.loads(line) for line in f if line.strip()]

    pages = []
    with open(pages_file, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                pages.append(json.loads(line))

    with_text = [p for p in pages if len(p.get("text_normalized", "").strip()) > 30]
    empty = [p for p in pages if len(p.get("text_normalized", "").strip()) <= 30]

    print("=" * 65)
    print(f"SHARD AUDIT: {shard_dir.name}")
    print("=" * 65)
    print(f"Total Books: {len(books)}")
    print(f"Total Pages: {len(pages)}")
    print(f"Pages with Real Text: {len(with_text)} ({len(with_text)/max(1, len(pages))*100:.1f}%)")
    print(f"Pure Image Scan Pages (Empty Text): {len(empty)} ({len(empty)/max(1, len(pages))*100:.1f}%)")

    if with_text:
        print("\n--- [Random Extracted Text Sample] ---")
        sample = random.choice(with_text)
        print(f"Page ID: {sample.get('id')}")
        print(f"Confidence: {sample.get('confidence')}")
        print(f"Extractor: {sample.get('extractor')}")
        print("Text Preview:")
        preview = sample.get("text_normalized", "")[:300].replace("\n", " ")
        print(f'"{preview}..."')
    print("=" * 65 + "\n")


def main():
    root = Path(__file__).resolve().parent.parent.parent
    shards_base = root / "data" / ".parallel_shards"
    
    for shard_path in sorted(shards_base.glob("shard_*")):
        audit_shard(shard_path)


if __name__ == "__main__":
    main()
