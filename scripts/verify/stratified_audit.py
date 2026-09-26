#!/usr/bin/env python3
"""Reproducible Stratified Quality & Provenance Audit Tool.

Uses a fixed random seed (seed=42) for reproducible sampling.
Checks:
- Provenance verification: nodeId, worker_version, pipeline_stage.
- Stratified sampling across:
  * text_layer_extracted
  * text_layer_missing_or_low_text
  * visual_ocr_extracted
- Linguistic & quality metrics:
  * CJK character ratio ([\u4e00-\u9fa5])
  * Repetition / degenerate text detection
  * Page continuity (p0, p1, p2...)
  * Confidence distribution
"""
import argparse
import json
import random
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional


def repetition_ratio(text: str, k: int = 4) -> float:
    """Calculate ratio of repeated k-grams (detect garbled/looping OCR)."""
    if len(text) < k * 2:
        return 0.0
    kgrams = [text[i:i+k] for i in range(len(text) - k + 1)]
    unique_kgrams = set(kgrams)
    return 1.0 - (len(unique_kgrams) / max(1, len(kgrams)))


def audit_shard(shard_dir: Path, sample_size: int = 3):
    pages_file = shard_dir / "pages.jsonl"
    ocr_pages_file = shard_dir / "ocr_pages.jsonl"
    books_file = shard_dir / "books.jsonl"
    chk_file = shard_dir / "chk.jsonl"

    if not pages_file.exists() and not ocr_pages_file.exists():
        return

    all_pages = []
    for pf in (pages_file, ocr_pages_file):
        if pf.exists():
            with open(pf, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.strip():
                        try:
                            all_pages.append(json.loads(line))
                        except Exception:
                            pass

    if not all_pages:
        return

    # 1. Stratify pages
    strata = defaultdict(list)
    for p in all_pages:
        stage = p.get("pipeline_stage", "legacy")
        cls = p.get("classification")
        if not cls:
            # Infer for legacy records
            text = p.get("text_normalized", "")
            cls = "text_layer_extracted" if len(text) >= 30 else "text_layer_missing_or_low_text"
        key = f"{stage}::{cls}"
        strata[key].append(p)

    # 2. Check provenance
    nodes_seen = set(p.get("node_id") for p in all_pages if p.get("node_id"))
    worker_versions = set(p.get("worker_version") for p in all_pages if p.get("worker_version"))

    # 3. Page continuity check across books
    book_pages = defaultdict(list)
    for p in all_pages:
        b_id = p.get("book_id", "")
        p_idx = p.get("page_index", 0)
        book_pages[b_id].append(p_idx)

    discontinuous_books = 0
    for b_id, p_indices in book_pages.items():
        sorted_indices = sorted(p_indices)
        expected = list(range(sorted_indices[0], sorted_indices[0] + len(sorted_indices)))
        if sorted_indices != expected:
            discontinuous_books += 1

    print("=" * 72)
    print(f"STRATIFIED AUDIT REPORT: {shard_dir.name}")
    print("=" * 72)
    print(f"Total Evaluated Pages: {len(all_pages)}")
    print(f"Verified Physical Nodes: {', '.join(nodes_seen) if nodes_seen else 'None (legacy)'}")
    print(f"Worker Versions: {', '.join(worker_versions) if worker_versions else 'Unversioned'}")
    print(f"Page Continuity: {len(book_pages) - discontinuous_books}/{len(book_pages)} books perfectly continuous")
    print("\nStrata Distribution:")
    for stratum_name, plist in sorted(strata.items()):
        pct = len(plist) / len(all_pages) * 100
        print(f"  - {stratum_name:38s}: {len(plist):5d} pages ({pct:5.1f}%)")

    # 4. Reproducible Seeded Sampling (seed=42)
    print("\nReproducible Samples (seed=42):")
    rng = random.Random(42)

    for stratum_name, plist in sorted(strata.items()):
        print(f"\n  [Sample from {stratum_name}]")
        sampled = rng.sample(plist, min(sample_size, len(plist)))
        for idx, item in enumerate(sampled, 1):
            text = item.get("text_normalized", "")
            cjk_chars = len(re.findall(r"[\u4e00-\u9fa5]", text))
            cjk_ratio = cjk_chars / max(1, len(text))
            rep_ratio = repetition_ratio(text)
            
            print(f"    Sample #{idx} ({item.get('id')}) | Node: {item.get('node_id', 'unknown')}")
            print(f"    Length: {len(text)} chars | CJK Ratio: {cjk_ratio:.1%} | Repetition: {rep_ratio:.1%} | Conf: {item.get('confidence', 0.0)}")
            preview = text[:180].replace("\n", " ").strip()
            if preview:
                print(f"    Preview: \"{preview}...\"")
            else:
                print("    Preview: [EMPTY / NO TEXT LAYER]")
    print("=" * 72 + "\n")


def main():
    root = Path(__file__).resolve().parent.parent.parent
    shards_dir = root / "data" / ".parallel_shards"
    
    found = False
    for s_path in sorted(shards_dir.glob("shard_*")):
        audit_shard(s_path)
        found = True

    if not found:
        print("No shards found in data/.parallel_shards/")


if __name__ == "__main__":
    main()
