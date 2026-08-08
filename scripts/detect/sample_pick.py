#!/usr/bin/env python3
"""
Sample Picker for M0 Validation

Selects 5-10 cross-category PDF samples for end-to-end validation.
Selection criteria:
  - Each status category represented (text_extractable, ocr_required, partial_text)
  - Diverse subcategories (marx-engels, philosophy, etc.)
  - Mix of file sizes (small <2MB, medium 2-20MB, large >20MB)
  - Total page count variety
"""

import json
import argparse
import random
from pathlib import Path
from collections import defaultdict


def load_detection_results(path: str) -> list[dict]:
    """Load detection results from JSONL file."""
    results = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                results.append(json.loads(line))
    return results


def pick_samples(results: list[dict], n: int = 10, seed: int = 42) -> list[dict]:
    """Pick N samples covering different categories and statuses."""
    random.seed(seed)
    
    # Group by status
    by_status = defaultdict(list)
    for r in results:
        by_status[r["status"]].append(r)
    
    # Shuffle each group
    for status in by_status:
        random.shuffle(by_status[status])
    
    samples = []
    
    # Priority 1: Ensure each status is represented
    # Order: text_extractable, ocr_required, partial_text, parser_error
    priority_order = ["text_extractable", "ocr_required", "partial_text", "parser_error"]
    for status in priority_order:
        if by_status[status]:
            samples.append(by_status[status].pop(0))
    
    # Priority 2: Pick diverse subcategories
    all_remaining = []
    for status in by_status:
        all_remaining.extend(by_status[status])
    
    # Group remaining by subcategory
    by_subcat = defaultdict(list)
    for r in all_remaining:
        by_subcat[r.get("subcategory", "unknown")].append(r)
    
    # Subcategories sorted by count (descending)
    sorted_subcats = sorted(by_subcat.keys(), key=lambda s: len(by_subcat[s]), reverse=True)
    
    for subcat in sorted_subcats:
        if len(samples) >= n:
            break
        if by_subcat[subcat]:
            samples.append(by_subcat[subcat][0])
    
    return samples[:n]


def assign_book_id(stem: str, existing_ids: set) -> str:
    """Assign a unique book_id from stem."""
    base = f"book-{stem}"
    if base not in existing_ids:
        existing_ids.add(base)
        return base
    # Handle collisions with suffix
    i = 1
    while f"{base}-{i}" in existing_ids:
        i += 1
    book_id = f"{base}-{i}"
    existing_ids.add(book_id)
    return book_id


def main():
    parser = argparse.ArgumentParser(description="Pick cross-category samples for M0")
    parser.add_argument("--input", default="data/manifest-detection.jsonl",
                        help="Input detection results JSONL")
    parser.add_argument("--output", default="data/manifest-samples.json",
                        help="Output JSON with selected samples")
    parser.add_argument("--count", type=int, default=10,
                        help="Number of samples to pick")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed for reproducibility")
    
    args = parser.parse_args()
    
    results = load_detection_results(args.input)
    print(f"Loaded {len(results)} detection results")
    
    # Show status distribution
    status_counts = defaultdict(int)
    for r in results:
        status_counts[r["status"]] += 1
    print("Status distribution:")
    for status, count in sorted(status_counts.items()):
        print(f"  {status:20s}: {count:4d}")
    
    samples = pick_samples(results, n=args.count, seed=args.seed)
    
    # Assign book_ids and add metadata
    existing_ids = set()
    for s in samples:
        s["book_id"] = assign_book_id(s.get("stem", "unknown"), existing_ids)
        s["sample_reason"] = []
        if s["status"] in ["text_extractable", "ocr_required", "partial_text"]:
            s["sample_reason"].append(f"type:{s['status']}")
        if s.get("subcategory"):
            s["sample_reason"].append(f"subcat:{s['subcategory']}")
    
    # Write output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(samples, f, ensure_ascii=False, indent=2)
    
    print(f"\nSelected {len(samples)} samples -> {output_path}")
    print(f"{'book_id':25s} | {'status':18s} | {'subcat':15s} | {'pages':>5s} | {'stem'}")
    print("-" * 85)
    for s in samples:
        print(f"{s['book_id']:25s} | {s['status']:18s} | {s.get('subcategory',''):15s} | {s.get('total_pages',0):5d} | {s.get('stem','')}")


if __name__ == "__main__":
    main()
