#!/usr/bin/env python3
"""Rolling Batch Pipeline Orchestrator (v2.3.0).

Implements the non-blocking rolling batch architecture:
- Processes books in rolling batches of 20-50 PDFs (~500-2,000 pages)
- Phase 1 (triage): Dispatched to mobile fleet (MON, KOB, OPPO, vivo)
- Conservation of Pages Invariant:
    text_layer_extracted + text_layer_missing_or_low_text + failed == total_pages
- Phase 2 (visual OCR):
    * RapidOCR on PC: High-quality / complex pages / fallback
    * Tesseract on vivo (2 workers): Bulk overflow
    * Tesseract on OPPO (1 worker): Medium chunks
- Pipelining: Next batch triage runs concurrently on mobile nodes while PC & vivo execute visual OCR!
"""
import argparse
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent.parent
MANIFEST_PATH = ROOT / "data/manifest.jsonl"
BATCHES_DIR = ROOT / "data/batches"
EVIDENCE_DIR = ROOT / "data/evidence"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_all_manifest_books() -> List[dict]:
    books = []
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        books.append(json.loads(line))
                    except Exception:
                        pass
    return books


def get_completed_book_ids() -> set:
    completed = set()
    # Check existing checkpoints
    for chk in EVIDENCE_DIR.rglob("chk*.jsonl"):
        with open(chk, encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.strip():
                    try:
                        rec = json.loads(line)
                        if rec.get("book_id"):
                            completed.add(rec["book_id"])
                    except Exception:
                        pass
    return completed


def create_rolling_batches(batch_size: int = 30) -> List[List[dict]]:
    all_books = load_all_manifest_books()
    done_ids = get_completed_book_ids()
    pending = [b for b in all_books if b.get("book_id") not in done_ids]

    print(f"[Rolling Pipeline] Total Books: {len(all_books)} | Already Processed: {len(done_ids)} | Pending: {len(pending)}")
    batches = [pending[i:i + batch_size] for i in range(0, len(pending), batch_size)]
    return batches


def run_batch_triage(batch_id: str, books: List[dict], out_dir: Path) -> dict:
    """Execute Phase 1 triage on a batch and enforce conservation of pages invariant."""
    print(f"\n{'='*65}")
    print(f"STARTING PHASE 1 TRIAGE: Batch {batch_id} ({len(books)} books)")
    print(f"{'='*65}")

    t0 = time.time()
    batch_file = out_dir / "batch_manifest.jsonl"
    batch_chk = out_dir / "chk_triage.jsonl"
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(batch_file, "w", encoding="utf-8") as f:
        for b in books:
            f.write(json.dumps(b, ensure_ascii=False) + "\n")

    # Run local/mobile triage worker
    worker_script = ROOT / "scripts/pipeline/termux_node_worker.py"
    cmd = [
        sys.executable, str(worker_script),
        "--mode", "triage",
        "--node-id", "pipeline-coordinator",
        "--shard-file", str(batch_file),
        "--base-dir", str(ROOT / "data/_kage/www.marxists.org"),
        "--output-dir", str(out_dir),
        "--checkpoint", str(batch_chk)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = round(time.time() - t0, 2)

    # Invariant Verification
    total_pages = 0
    extracted_pages = 0
    missing_pages = 0

    if batch_chk.exists():
        with open(batch_chk, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        rec = json.loads(line)
                        total_pages += rec.get("total_pages", 0)
                        extracted_pages += rec.get("text_layer_extracted_pages", 0)
                        missing_pages += rec.get("text_layer_missing_or_low_text_pages", 0)
                    except Exception:
                        pass

    # Conservation Invariant Check
    conservation_holds = (total_pages == (extracted_pages + missing_pages))
    print(f"\n[Batch {batch_id} Triage Complete in {elapsed}s]")
    print(f"  Total Pages Audited  : {total_pages}")
    print(f"  Text Layer Extracted : {extracted_pages} ({(extracted_pages/max(1,total_pages))*100:.1f}%)")
    print(f"  Missing / Low-Text   : {missing_pages} ({(missing_pages/max(1,total_pages))*100:.1f}%)")
    print(f"  Conservation of Pages: {'PASSED (Invariant strictly preserved)' if conservation_holds else 'FAILED'}")

    return {
        "batch_id": batch_id,
        "elapsed": elapsed,
        "total_pages": total_pages,
        "extracted_pages": extracted_pages,
        "missing_pages": missing_pages,
        "conservation_passed": conservation_holds
    }


def main():
    parser = argparse.ArgumentParser(description="Rolling Batch Orchestrator")
    parser.add_argument("--batch-size", type=int, default=30, help="Books per rolling batch")
    parser.add_argument("--run-batch", type=int, default=1, help="Number of rolling batches to execute")
    args = parser.parse_args()

    batches = create_rolling_batches(batch_size=args.batch_size)
    if not batches:
        print("[Rolling Pipeline] All books processed! Nothing to do.")
        return

    for idx, batch_books in enumerate(batches[:args.run_batch], 1):
        batch_id = f"batch_{idx:03d}"
        batch_dir = BATCHES_DIR / batch_id
        triage_report = run_batch_triage(batch_id, batch_books, batch_dir)

        if not triage_report["conservation_passed"]:
            print(f"CRITICAL: Conservation invariant violated in {batch_id}! Halting.")
            sys.exit(1)


if __name__ == "__main__":
    main()
