#!/usr/bin/env python3
"""Generate 5 balanced manifest shards for PC and 4 Mobile Fleet Nodes.

Nodes:
- Shard 0 (PC): Heavy / high page count OCR books
- Shard 1 (vivo-worker): High memory (11GB) 100-250 pages OCR books
- Shard 2 (oppo-service): General compute (155GB storage) 50-120 pages books
- Shard 3 (mon-worker): Single concurrency partial_text + lightweight OCR
- Shard 4 (kob-worker): Single concurrency small books + text normalization
"""
import json
import os
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent.parent.parent
    manifest_path = root / "data" / "manifest.jsonl"
    checkpoint_path = root / "data" / "batch_checkpoint.jsonl"
    shards_dir = root / "data" / "fleet_shards"
    shards_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load completed book IDs from checkpoint
    completed_ids = set()
    if checkpoint_path.exists():
        with open(checkpoint_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("status") == "success":
                        completed_ids.add(rec.get("book_id"))
                except Exception:
                    pass

    print(f"Loaded {len(completed_ids)} completed books from checkpoint.")

    # 2. Load all manifest entries
    all_books = []
    with open(manifest_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            all_books.append(json.loads(line))

    # 3. Filter pending books
    pending = [b for b in all_books if b["book_id"] not in completed_ids]
    print(f"Total manifest books: {len(all_books)}, Pending to process: {len(pending)}")

    # Sort pending books by status (partial_text first, then ocr_required) and page_count desc
    partial_text = [b for b in pending if b.get("status") == "partial_text"]
    ocr_required = [b for b in pending if b.get("status") == "ocr_required"]
    others = [b for b in pending if b not in partial_text and b not in ocr_required]

    # Sort OCR books by page count descending
    ocr_required.sort(key=lambda x: x.get("page_count", 0), reverse=True)
    partial_text.sort(key=lambda x: x.get("page_count", 0), reverse=True)

    # Shard buckets
    shards = {
        "shard_0_pc": [],
        "shard_1_vivo": [],
        "shard_2_oppo": [],
        "shard_3_mon": [],
        "shard_4_kob": []
    }

    # Assign partial_text books: small ones to mon/kob, larger to oppo/vivo/pc
    for i, b in enumerate(partial_text):
        pages = b.get("page_count", 0)
        if pages <= 50:
            if len(shards["shard_3_mon"]) <= len(shards["shard_4_kob"]):
                shards["shard_3_mon"].append(b)
            else:
                shards["shard_4_kob"].append(b)
        elif pages <= 150:
            shards["shard_2_oppo"].append(b)
        else:
            shards["shard_1_vivo"].append(b)

    # Assign ocr_required books based on page count and power
    # Top heavy books (>250 pages) -> PC
    # Mid-heavy books (100-250 pages) -> vivo
    # Mid books (50-100 pages) -> oppo
    # Small books (<50 pages) -> mon and kob
    for b in ocr_required:
        pages = b.get("page_count", 0)
        if pages >= 220:
            shards["shard_0_pc"].append(b)
        elif pages >= 100:
            shards["shard_1_vivo"].append(b)
        elif pages >= 40:
            shards["shard_2_oppo"].append(b)
        elif pages >= 20:
            shards["shard_3_mon"].append(b)
        else:
            shards["shard_4_kob"].append(b)

    # Assign any others
    for b in others:
        shards["shard_0_pc"].append(b)

    # Output shard files and statistics
    print("\n" + "=" * 60)
    print("FLEET SHARDING SUMMARY:")
    print("=" * 60)
    for shard_name, books in shards.items():
        total_pages = sum(b.get("page_count", 0) for b in books)
        total_mb = sum(b.get("size_bytes", 0) for b in books) / (1024 * 1024)
        out_file = shards_dir / f"{shard_name}.jsonl"
        with open(out_file, "w", encoding="utf-8") as f:
            for b in books:
                f.write(json.dumps(b, ensure_ascii=False) + "\n")
        print(f"[{shard_name:14s}] Books: {len(books):4d} | Pages: {total_pages:6d} | Size: {total_mb:7.1f} MB -> {out_file.name}")
    print("=" * 60)


if __name__ == "__main__":
    main()
