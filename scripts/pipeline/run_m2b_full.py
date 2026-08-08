"""M2b Full Pipeline Orchestrator.

Runs text_extractable first (fast), then hands off to parallel OCR for
ocr_required + partial_text when text_extractable completes.

Usage:
    python scripts/pipeline/run_m2b_full.py              # run full pipeline
    python scripts/pipeline/run_m2b_full.py --status text_extractable  # single phase
    python scripts/pipeline/run_m2b_full.py --dry-plan   # show plan without running
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from collections import Counter


def load_manifest(path):
    recs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                recs.append(json.loads(line))
    return recs


def checkpoint_stats(cp_path):
    """Return counts from existing checkpoint."""
    if not os.path.exists(cp_path):
        return {"success": 0, "error": 0, "total": 0}
    stats = {"success": 0, "error": 0, "total": 0}
    with open(cp_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                stats["total"] += 1
                if rec.get("status") == "success":
                    stats["success"] += 1
                elif rec.get("status") == "error":
                    stats["error"] += 1
            except Exception:
                pass
    return stats


def make_parser():
    parser = argparse.ArgumentParser(description="M2b full pipeline orchestrator")
    parser.add_argument("--manifest", default="data/manifest.jsonl")
    parser.add_argument("--base-dir", default="data/_kage/www.marxists.org")
    parser.add_argument("--status", default=None,
                        help="Single status to run (otherwise runs all phases)")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--max-pages-per-book", type=int, default=0)
    parser.add_argument("--poppler-path", default=None)
    parser.add_argument("--dry-plan", action="store_true")
    return parser


def run_phase(statuses, args, evidence_dir, checkpoint_path, parallel=False):
    """Run a batch_ingest phase for the given statuses.
    
    Returns True on success.
    """
    status_filter = ",".join(statuses)
    
    if parallel and len(statuses) > 0:
        # Use batch_parallel.py for parallel processing
        cmd = [
            sys.executable,
            str(Path(__file__).resolve().parent / "batch_parallel.py"),
            "--workers", str(args.workers),
            "--status-filter", status_filter,
            "--manifest", args.manifest,
            "--base-dir", args.base_dir,
            "--dpi", str(args.dpi),
            "--shards-dir", "data/.parallel_shards",
        ]
        if args.poppler_path:
            cmd += ["--poppler-path", args.poppler_path]
        if args.max_pages_per_book > 0:
            cmd += ["--max-pages-per-book", str(args.max_pages_per_book)]
    else:
        # Use batch_ingest.py for sequential processing
        cmd = [
            sys.executable,
            str(Path(__file__).resolve().parent / "batch_ingest.py"),
            "--status-filter", status_filter,
            "--manifest", args.manifest,
            "--base-dir", args.base_dir,
            "--output-dir", evidence_dir,
            "--checkpoint", checkpoint_path,
            "--dpi", str(args.dpi),
        ]
        if args.poppler_path:
            cmd += ["--poppler-path", args.poppler_path]
        if args.max_pages_per_book > 0:
            cmd += ["--max-pages-per-book", str(args.max_pages_per_book)]
    
    print(f"\n=== PHASE: {status_filter} ({'parallel' if parallel else 'sequential'}) ===", file=sys.stderr)
    print(f"  Command: {' '.join(cmd)}", file=sys.stderr, flush=True)
    
    proc = subprocess.run(cmd)
    return proc.returncode == 0


def main():
    parser = make_parser()
    args = parser.parse_args()
    
    manifest = load_manifest(args.manifest)
    print(f"Manifest: {len(manifest)} books", file=sys.stderr)
    
    # Status distribution
    status_counts = Counter(r.get("status") for r in manifest)
    print(f"Status distribution: {dict(status_counts)}", file=sys.stderr)
    
    evidence_dir = "data/evidence"
    checkpoint_path = "data/batch_checkpoint.jsonl"
    
    # Current checkpoint stats
    cs = checkpoint_stats(checkpoint_path)
    print(f"Checkpoint: {cs['success']} success, {cs['error']} error", file=sys.stderr)
    
    if args.dry_plan:
        print("\nPlan:", file=sys.stderr)
        print("  Phase 1: text_extractable (136 books, sequential, ~5-6 hours)", file=sys.stderr)
        print("  Phase 2: partial_text + ocr_required (1318 books, parallel, ~2-3 days @ 4 workers)", file=sys.stderr)
        print("  Then: data/catalog/load_catalog.py to build SQLite index", file=sys.stderr)
        return
    
    # Determine which statuses to run
    if args.status:
        statuses_to_run = [args.status]
    else:
        statuses_to_run = ["text_extractable", "partial_text", "ocr_required", "parser_error"]
    
    # Run phases
    start = time.time()
    for status in statuses_to_run:
        if status == "text_extractable":
            # Sequential for reliability
            ok = run_phase(["text_extractable"], args, evidence_dir, checkpoint_path, parallel=False)
        elif status in ("partial_text", "ocr_required"):
            # Parallel for OCR-bound workloads
            ok = run_phase(["partial_text", "ocr_required"], args, evidence_dir, checkpoint_path, parallel=True)
        else:
            ok = run_phase([status], args, evidence_dir, checkpoint_path, parallel=False)
        
        if not ok:
            print(f"PHASE FAILED: {status}. Check logs and rerun.", file=sys.stderr)
            sys.exit(1)
        
        cs = checkpoint_stats(checkpoint_path)
        elapsed = time.time() - start
        print(f"Phase done: {status}. Checkpoint: {cs['success']} ok / {cs['error']} err. Elapsed: {elapsed/60:.1f} min", file=sys.stderr)
    
    print(f"\nAll phases complete. Total: {time.time()-start:.1f}s", file=sys.stderr)
    print(f"Run: python scripts/catalog/load_catalog.py --evidence-dir data/evidence --db data/catalog/catalog.db", file=sys.stderr)


if __name__ == "__main__":
    main()
