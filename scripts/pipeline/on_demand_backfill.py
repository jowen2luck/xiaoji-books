#!/usr/bin/env python3
"""
on_demand_backfill.py — On-Demand Precision Layout Backfill Engine.

Strategy:
  Instead of wasteful overnight mass OCR across hundreds of unread books,
  trigger high-precision RapidOCR + LayoutAnalyzer on-demand when a user
  actually inspects, reads, or retrieves original text of a book.

Lifecycle:
  1. If book is already Tier 3 (navigation/<book_id>/doc_meta.json exists),
     returns immediately without any OCR cost.
  2. If book has blocks in existing shards (Tier 2.5), runs zero-OCR LayoutAnalyzer
     reconstruction (taking ~2-5 seconds).
  3. If book is Tier 1/2 (pure text in catalog/corpus) or Tier 0:
     - Locates PDF via data/manifest.jsonl.
     - Runs process_pdf_ocr with RapidOCR + LayoutAnalyzer.
     - Generates blocks.jsonl, page_structure.jsonl, paragraphs_v2.jsonl, doc_meta.json.
     - Elevates data quality to Tier 3 permanently.
"""

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ocr_extract import process_pdf_ocr
from block_structure import process_book, load_blocks_for_book

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
MANIFEST_PATH = ROOT_DIR / "data/manifest.jsonl"
NAVIGATION_DIR = ROOT_DIR / "data/evidence/navigation"
SHARD_PATHS = [
    ROOT_DIR / f"data/evidence/shard{i}/blocks.jsonl" for i in range(1, 5)
]


def find_pdf_for_book(book_id: str) -> Optional[Path]:
    """Find local PDF path for book_id from manifest.jsonl."""
    if not MANIFEST_PATH.exists():
        return None
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            if item.get("book_id") == book_id:
                # 1. Try source_full_path
                full_path_str = item.get("source_full_path")
                if full_path_str:
                    p = Path(full_path_str)
                    if p.is_absolute() and p.exists():
                        return p
                    rel_p = ROOT_DIR / full_path_str
                    if rel_p.exists():
                        return rel_p
                # 2. Try source_path
                src_path_str = item.get("source_path")
                if src_path_str:
                    candidates = [
                        ROOT_DIR / src_path_str,
                        ROOT_DIR / "data" / src_path_str,
                        ROOT_DIR / "data/_kage/www.marxists.org" / src_path_str,
                    ]
                    for c in candidates:
                        if c.exists():
                            return c
    return None


def check_tier_status(book_id: str, output_dir: Path = NAVIGATION_DIR) -> Dict:
    """Check current Tier status for a book."""
    book_nav_dir = output_dir / book_id
    doc_meta_file = book_nav_dir / "doc_meta.json"
    
    if doc_meta_file.exists():
        try:
            with open(doc_meta_file, encoding="utf-8") as f:
                meta = json.load(f)
            return {
                "tier": "Tier 3",
                "tier_name": "Gold (Full Layout & 4-Point Bbox)",
                "ready": True,
                "meta": meta,
            }
        except Exception:
            pass

    # Check if blocks exist in shards
    shard_blocks = load_blocks_for_book(book_id, [str(p) for p in SHARD_PATHS])
    if shard_blocks:
        return {
            "tier": "Tier 2.5",
            "tier_name": "Shard Blocks Ready (Offline Rebuild Needed)",
            "ready": False,
            "block_count": len(shard_blocks),
        }

    return {
        "tier": "Tier 1/2",
        "tier_name": "Text Only (Requires On-Demand Precision OCR)",
        "ready": False,
    }


def backfill_book(
    book_id: str,
    max_pages: Optional[int] = None,
    dpi: int = 200,
    force: bool = False,
    output_dir: Path = NAVIGATION_DIR,
) -> Dict:
    """Execute on-demand precision backfill for a single book."""
    t0 = time.time()
    book_nav_dir = output_dir / book_id
    doc_meta_file = book_nav_dir / "doc_meta.json"

    # Step 1: Check if already Tier 3
    if doc_meta_file.exists() and not force:
        with open(doc_meta_file, encoding="utf-8") as f:
            meta = json.load(f)
        return {
            "status": "already_tier3",
            "book_id": book_id,
            "duration_seconds": round(time.time() - t0, 3),
            "meta": meta,
        }

    # Step 2: Check if blocks exist in shards
    shard_blocks = load_blocks_for_book(book_id, [str(p) for p in SHARD_PATHS])
    if shard_blocks and not force:
        print(f"[{book_id}] Found {len(shard_blocks)} blocks in shards. Running zero-OCR layout analyzer...", file=sys.stderr)
        meta = process_book(book_id, shard_blocks, str(output_dir))
        return {
            "status": "upgraded_from_shards",
            "book_id": book_id,
            "duration_seconds": round(time.time() - t0, 3),
            "meta": meta,
        }

    # Step 3: Full precision OCR on-demand
    pdf_path = find_pdf_for_book(book_id)
    if not pdf_path or not pdf_path.exists():
        return {
            "status": "error",
            "book_id": book_id,
            "error": f"Source PDF file not found for book_id '{book_id}'",
        }

    print(f"[{book_id}] Backfilling from source PDF: {pdf_path.name} (dpi={dpi}, max_pages={max_pages})...", file=sys.stderr)
    ocr_result = process_pdf_ocr(
        str(pdf_path),
        book_id=book_id,
        dpi=dpi,
        max_pages=max_pages,
        return_blocks=True,
        analyze_layout=True,
    )

    # Flatten blocks and assign unique IDs
    all_blocks = []
    es_hash = hashlib.md5(f"{book_id}:{pdf_path.name}".encode("utf-8")).hexdigest()[:16]

    for p in ocr_result.get("pages", []):
        pi = p["page_index"]
        for b_idx, b in enumerate(p.get("blocks", [])):
            box = b.get("box")
            if not box:
                continue
            all_blocks.append({
                "id": f"{book_id}:p{pi}:b{b_idx}:es-{es_hash}",
                "book_id": book_id,
                "page_index": pi,
                "box": box,
                "text_raw": b.get("text", ""),
                "confidence": round(float(b.get("confidence", 1.0)), 4),
            })

    # Save blocks.jsonl in navigation folder
    book_nav_dir.mkdir(parents=True, exist_ok=True)
    blocks_file = book_nav_dir / "blocks.jsonl"
    with open(blocks_file, "w", encoding="utf-8") as f:
        for b in all_blocks:
            f.write(json.dumps(b, ensure_ascii=False) + "\n")

    # Run layout structuring to produce page_structure.jsonl, paragraphs_v2.jsonl, doc_meta.json
    meta = process_book(book_id, all_blocks, str(output_dir))

    duration = round(time.time() - t0, 3)
    print(f"[{book_id}] On-demand backfill completed in {duration}s: {meta['total_pages']} pages, {meta['total_paragraphs']} paras, {meta['total_headings']} headings.", file=sys.stderr)

    return {
        "status": "backfilled_tier3",
        "book_id": book_id,
        "duration_seconds": duration,
        "meta": meta,
    }


def main():
    parser = argparse.ArgumentParser(description="On-demand layout backfill engine")
    parser.add_argument("--book-id", required=True, help="Book ID to backfill")
    parser.add_argument("--max-pages", type=int, default=None, help="Limit number of pages")
    parser.add_argument("--dpi", type=int, default=200, help="Rasterization DPI")
    parser.add_argument("--force", action="store_true", help="Force re-extraction")
    parser.add_argument("--check-only", action="store_true", help="Only check Tier status without backfilling")
    parser.add_argument("--json", action="store_true", help="Output pure JSON")
    args = parser.parse_args()

    if args.check_only:
        status = check_tier_status(args.book_id)
        if args.json:
            print(json.dumps(status, ensure_ascii=False, indent=2))
        else:
            print(f"Book: {args.book_id} | Status: {status['tier']} - {status['tier_name']}")
        return

    result = backfill_book(
        book_id=args.book_id,
        max_pages=args.max_pages,
        dpi=args.dpi,
        force=args.force,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Result: {result['status']} ({result.get('duration_seconds', 0)}s)")


if __name__ == "__main__":
    main()
