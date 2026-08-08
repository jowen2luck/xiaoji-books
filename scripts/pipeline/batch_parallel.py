"""Parallel batch runner — shards manifest across workers for OCR scaling.

Runs N worker processes, each processing a subset of the manifest into its own
evidence shard. Individual book errors are isolated; checkpoint is book-level.

Usage (start parallel batch):
    python scripts/pipeline/batch_parallel.py --workers 4 --status-filter ocr_required

Usage (merge shards into single evidence/):
    python scripts/pipeline/batch_parallel.py --merge
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def make_parser():
    parser = argparse.ArgumentParser(description="Parallel batch OCR via sharding")
    parser.add_argument("--workers", type=int, default=4,
                        help="Number of parallel worker processes")
    parser.add_argument("--status-filter", default="ocr_required",
                        help="Same filter as batch_ingest.py")
    parser.add_argument("--manifest", default="data/manifest.jsonl")
    parser.add_argument("--base-dir", default="data/_kage/www.marxists.org")
    parser.add_argument("--max-pages-per-book", type=int, default=0,
                        help=">0: cap pages per book")
    parser.add_argument("--limit-per-worker", type=int, default=0,
                        help=">0: cap books per worker (testing)")
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--poppler-path", default=None)
    parser.add_argument("--shards-dir", default="data/.shards",
                        help="Working directory for shard outputs")
    parser.add_argument("--merge", action="store_true",
                        help="Merge existing shards into data/evidence")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--worker-timeout", type=int, default=0,
                        help="Max seconds per worker (0=no limit)")
    return parser


def load_manifest(path):
    recs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                recs.append(json.loads(line))
    return recs


def write_jsonl_shard(records, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def merge_shards_into_evidence(shards_dir, target_dir, checkpoint_path):
    """Merge shard output JSONLs into a single evidence dir, dedup by (book_id, evidence_set_id)."""
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    
    # Merge each type
    merged_pages = {}  # id -> record
    merged_paras = {}
    merged_books = {}
    
    shards_d = Path(shards_dir)
    if not shards_d.exists():
        print(f"Shards dir not found: {shards_dir}", file=sys.stderr)
        return 0, 0
    
    total_merged = 0
    for shard_dir in sorted(shards_d.iterdir()):
        if not shard_dir.is_dir():
            continue
        for fname in ("books.jsonl", "pages.jsonl", "paragraphs.jsonl"):
            src = shard_dir / fname
            if not src.exists():
                continue
            with open(src, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        rid = rec.get("id") or rec.get("book_id")
                        es = rec.get("evidence_set_id", "")
                        key = (rid, es)
                        if fname == "books.jsonl":
                            if key not in merged_books:
                                merged_books[key] = rec
                                total_merged += 1
                        elif fname == "pages.jsonl":
                            if key not in merged_pages:
                                merged_pages[key] = rec
                                total_merged += 1
                        elif fname == "paragraphs.jsonl":
                            if key not in merged_paras:
                                merged_paras[key] = rec
                                total_merged += 1
                    except Exception:
                        pass
    
    # Write merged
    for fname, data in [("books.jsonl", merged_books), ("pages.jsonl", merged_pages), ("paragraphs.jsonl", merged_paras)]:
        with open(target / fname, "w", encoding="utf-8") as f:
            for rec in data.values():
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    
    # Merge checkpoint (dedup by book_id+evidence_set_id success entries)
    cp_entries = {}
    for shard_dir in sorted(shards_d.iterdir()):
        cp_src = shard_dir / "checkpoint.jsonl"
        if not cp_src.exists():
            continue
        with open(cp_src, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    bid = rec.get("book_id", "")
                    esid = rec.get("evidence_set_id", "")
                    key = (bid, esid)
                    cp_entries[key] = rec
                except Exception:
                    pass
    
    cp_dir = Path(checkpoint_path).parent
    cp_dir.mkdir(parents=True, exist_ok=True)
    # Append to existing checkpoint instead of overwrite (idempotent)
    with open(checkpoint_path, "a", encoding="utf-8") as f:
        for rec in cp_entries.values():
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    
    return total_merged, len(cp_entries)


def main():
    parser = make_parser()
    args = parser.parse_args()

    if args.merge:
        merged, cp = merge_shards_into_evidence(
            args.shards_dir, "data/evidence", "data/batch_checkpoint.jsonl"
        )
        print(f"Merged {merged} records, {cp} checkpoint entries", file=sys.stderr)
        return

    # Load and filter manifest
    manifest = load_manifest(args.manifest)
    target_statuses = set(s.strip() for s in args.status_filter.split(","))
    targets = [r for r in manifest if r.get("status") in target_statuses]
    print(f"Manifest: {len(manifest)}, filter={args.status_filter}, targets={len(targets)}", file=sys.stderr)

    if args.limit_per_worker:
        targets = targets[:args.limit_per_worker * args.workers]

    # Shard
    n = args.workers
    shards = [[] for _ in range(n)]
    # Size-aware sharding: distribute by cumulative page count for even load
    targets_sorted = sorted(targets, key=lambda r: r.get("page_count", 100), reverse=True)
    shard_loads = [0] * n
    for rec in targets_sorted:
        min_shard = shard_loads.index(min(shard_loads))
        shards[min_shard].append(rec)
        shard_loads[min_shard] += rec.get("page_count", 100)

    for i, s in enumerate(shards):
        print(f"  Shard {i+1}: {len(s)} books, {shard_loads[i]} pages", file=sys.stderr)

    shards_dir = Path(args.shards_dir)
    if shards_dir.exists():
        shutil.rmtree(str(shards_dir))
    shards_dir.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        for i, s in enumerate(shards):
            write_jsonl_shard(s, str(shards_dir / f"shard-{i+1}" / "manifest.jsonl"))
        print("Dry-run: manifest shards written", file=sys.stderr)
        return

    # Spawn workers
    # Use sys.executable to get the same python that called this script
    py = sys.executable
    script = Path(__file__).resolve().parent / "batch_ingest.py"
    
    procs = []
    for i, shard_records in enumerate(shards):
        if not shard_records:
            continue
        shard_dir = shards_dir / f"shard-{i+1}"
        shard_dir.mkdir(parents=True, exist_ok=True)
        shard_manifest = shard_dir / "manifest.jsonl"
        write_jsonl_shard(shard_records, str(shard_manifest))
        
        cmd = [
            py, str(script),
            "--manifest", str(shard_manifest),
            "--base-dir", args.base_dir,
            "--status-filter", args.status_filter,
            "--output-dir", str(shard_dir / "evidence"),
            "--checkpoint", str(shard_dir / "checkpoint.jsonl"),
            "--dpi", str(args.dpi),
        ]
        if args.poppler_path:
            cmd += ["--poppler-path", args.poppler_path]
        if args.max_pages_per_book > 0:
            cmd += ["--max-pages-per-book", str(args.max_pages_per_book)]
        
        print(f"  Starting worker {i+1} ({len(shard_records)} books)", file=sys.stderr)
        logfile = open(shard_dir / "worker.log", "w", encoding="utf-8")
        p = subprocess.Popen(cmd, stdout=logfile, stderr=logfile)
        procs.append((i+1, p, logfile))

    # Wait for completion with timeout
    print(f"\nWaiting for {len(procs)} workers...", file=sys.stderr, flush=True)
    
    start = time.time()
    results = {}
    while procs:
        for wid, p, logfile in list(procs):
            ret = p.poll()
            if ret is not None:
                elapsed = time.time() - start
                results[wid] = ret
                procs.remove((wid, p, logfile))
                logfile.close()
                status = "OK" if ret == 0 else f"FAIL({ret})"
                print(f"  Worker {wid} finished: {status} ({elapsed:.1f}s)", file=sys.stderr, flush=True)
        if procs:
            time.sleep(10)
        
        if args.worker_timeout and (time.time() - start) > args.worker_timeout:
            print(f"Timeout! Killing remaining {len(procs)} workers", file=sys.stderr)
            for wid, p, logfile in procs:
                p.kill()
                logfile.close()
                results[wid] = "TIMEOUT"
            procs.clear()

    # Merge
    all_ok = all(r == 0 for r in results.values())
    if all_ok:
        print("\nAll workers completed successfully. Merging shards...", file=sys.stderr)
        merged, cp = merge_shards_into_evidence(
            args.shards_dir, "data/evidence", "data/batch_checkpoint.jsonl"
        )
        print(f"Merged: {merged} records, {cp} checkpoint entries", file=sys.stderr)
        # Clean up shards after merge
        # shutil.rmtree(str(shards_dir))
    else:
        print(f"\nSome workers failed: {results}. Shards preserved at {args.shards_dir}", file=sys.stderr)
        print(f"Fix failed shards then run: python {sys.argv[0]} --merge", file=sys.stderr)


if __name__ == "__main__":
    main()
