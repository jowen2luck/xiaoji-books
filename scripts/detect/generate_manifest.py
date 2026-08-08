#!/usr/bin/env python3
"""
M1: Generate stable book_id manifest (v2 — archive_id-based identity).

Reads archive-index.json + manifest-detection.jsonl
Produces data/manifest.jsonl with:
  - book_id: stable, unique, NEVER changes (bound to archive_id)
  - artifact_id: SHA-256 of current file content
  - source_path: current file location (mutable)
  - aliases: stem + archive_id for backward compat
  - status: detection classification
  - archive_id: permanent unique key from archive-index

CRITICAL FIX (v2): Detection lookup uses archive_id (unique), not stem (may collide).
Duplicate stem suffix assignment also sorts by archive_id for stability.
"""

import json
import os
import sys
import hashlib
import argparse
from pathlib import Path
from collections import defaultdict, Counter


def read_archive_index(index_path: str) -> list[dict]:
    """Read archive-index.json, return only PDF entries."""
    with open(index_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [e for e in data.get("files", []) if e.get("type") == "pdf"]


def read_detection_results(detection_path: str) -> dict:
    """Read manifest-detection.jsonl into multi-key lookup.
    
    Returns dict with keys:
      - 'by_archive_id': {archive_id: record}  ← PRIMARY key (always unique)
      - 'by_file_path': {file_path: record}     ← secondary key
      - 'by_stem':      {stem: [records]}       ← for diagnostics only
    """
    results = {
        "by_archive_id": {},
        "by_file_path": {},
        "by_stem": defaultdict(list),
    }
    with open(detection_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            archive_id = record.get("archive_id", "")
            file_path = record.get("file_path", "")
            stem = record.get("stem", "")
            if archive_id:
                results["by_archive_id"][archive_id] = record
            if file_path:
                results["by_file_path"][file_path] = record
            if stem:
                results["by_stem"][stem].append(record)
    return results


def lookup_detection(detection_results: dict, archive_id: str = "", file_path: str = "") -> dict:
    """Look up detection record by archive_id (primary) or file_path (fallback)."""
    # Primary: by archive_id
    if archive_id:
        rec = detection_results["by_archive_id"].get(archive_id)
        if rec:
            return rec
    # Fallback: by file_path
    if file_path:
        rec = detection_results["by_file_path"].get(file_path)
        if rec:
            return rec
    return {}


def compute_sha256(file_path: str) -> str:
    """Compute SHA-256 of file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def find_duplicate_stems(entries: list[dict]) -> dict[str, list[dict]]:
    """Find stems that appear more than once."""
    stem_groups = defaultdict(list)
    for entry in entries:
        stem_groups[entry.get("stem", "")].append(entry)
    return {s: g for s, g in stem_groups.items() if len(g) > 1}


def assign_book_id(stem: str, existing_ids: set) -> str:
    """Assign a unique book_id by stem.
    
    First: book-{stem}
    Collision: book-{stem}-{n} (n=2,3,...)
    """
    base = f"book-{stem}"
    if base not in existing_ids:
        candidate = base
    else:
        i = 2
        while f"{base}-{i}" in existing_ids:
            i += 1
        candidate = f"{base}-{i}"
    existing_ids.add(candidate)
    return candidate


def sort_entries_for_stable_id(all_entries: list[dict]) -> list[dict]:
    """Sort entries so duplicate-stem ID assignment is stable across runs.
    
    Sort key: (stem, archive_id) — same stem, same archive_id ordering = same ID assignment.
    """
    return sorted(all_entries, key=lambda e: (e.get("stem", ""), e.get("id", "")))


def generate_manifest(
    archive_entries: list[dict],
    detection_results: dict,
    source_dir: str,
) -> tuple[list[dict], dict]:
    """
    Generate stable manifest records.
    
    Identity rule:
      1. Detection lookup: archive_id (unique) — NEVER use stem for join.
      2. book_id assignment: sort by (stem, archive_id) then assign in order,
         so duplicate stem suffix is stable regardless of input order.
    """
    stats = {
        "total": 0,
        "unique_stems": 0,
        "duplicate_stems": 0,
        "duplicate_entries": 0,
        "id_collisions_fixed": 0,
        "missing_detection": 0,
        "missing_file": 0,
        "errors": [],
    }

    existing_ids = set()
    manifest = []
    
    # Sort entries for stable ID assignment
    sorted_entries = sort_entries_for_stable_id(archive_entries)

    for entry in sorted_entries:
        stem = entry.get("stem", "")
        entry_id = entry.get("id", "")
        rel_path = entry.get("path", "")
        file_path = Path(source_dir) / rel_path.replace("\\", os.sep).replace("/", os.sep)

        stats["total"] += 1

        # Detection status — use archive_id (ALWAYS unique), fallback to file_path
        det = lookup_detection(detection_results, archive_id=entry_id, file_path=str(file_path))
        status = det.get("status", "")
        if not status:
            stats["missing_detection"] += 1
            status = "unknown"

        # Compute artifact_id (SHA-256 of current file)
        artifact_id = ""
        if file_path.exists():
            try:
                artifact_id = f"sha256:{compute_sha256(str(file_path))}"
            except Exception as e:
                stats["errors"].append(f"Hash failed for {entry_id}: {e}")
        else:
            stats["missing_file"] += 1

        # Assign book_id (stable)
        book_id = assign_book_id(stem, existing_ids)
        if book_id != f"book-{stem}":
            stats["id_collisions_fixed"] += 1

        # Build manifest record
        record = {
            "book_id": book_id,
            "artifact_id": artifact_id,
            "source_path": rel_path.replace("\\", "/"),
            "source_full_path": str(file_path),
            "status": status,
            "aliases": list(filter(None, [stem, entry_id])),
            "stem": stem,
            "archive_id": entry_id,
            "page_count": det.get("total_pages", 0),
            "size_bytes": entry.get("size_bytes", 0),
            "subcategory": entry.get("subcategory", ""),
        }

        manifest.append(record)

    # Stats
    stem_counter = Counter(e.get("stem", "") for e in archive_entries)
    stats["unique_stems"] = len(stem_counter)
    stats["duplicate_stems"] = sum(1 for c in stem_counter.values() if c > 1)
    stats["duplicate_entries"] = sum(c - 1 for c in stem_counter.values() if c > 1)

    return manifest, stats


def main():
    parser = argparse.ArgumentParser(description="Generate stable book_id manifest (v2)")
    parser.add_argument("--index", default="data/archive-index.json")
    parser.add_argument("--detection", default="data/manifest-detection.jsonl")
    parser.add_argument("--source-dir", default="data/_kage/www.marxists.org")
    parser.add_argument("--output", default="data/manifest.jsonl")
    parser.add_argument("--stats-output", default="data/manifest-stats.json")
    args = parser.parse_args()

    # Read inputs
    print("Reading archive-index.json...")
    archive_entries = read_archive_index(args.index)
    print(f"  {len(archive_entries)} PDF entries in archive-index")

    print("Reading detection results...")
    detection_results = read_detection_results(args.detection)
    print(f"  {len(detection_results['by_archive_id'])} by archive_id, "
          f"{len(detection_results['by_file_path'])} by file_path")

    # Find duplicates upfront
    dup_stems = {}
    stem_counter = Counter(e.get("stem", "") for e in archive_entries)
    for stem, count in stem_counter.most_common():
        if count > 1:
            dup_stems[stem] = count

    if dup_stems:
        print(f"\n⚠ Found {len(dup_stems)} stems with duplicate entries:")
        print(f"  Total extra entries: {sum(c-1 for c in dup_stems.values())}")

    # Check: do all archive_ids have detection?
    missing_det = [e for e in archive_entries if e.get("id") not in detection_results["by_archive_id"]]
    if missing_det:
        print(f"\n⚠ {len(missing_det)} archive entries have NO detection record!")
        for m in missing_det[:3]:
            print(f"    id={m.get('id')}")

    # Generate manifest
    print("\nGenerating manifest...")
    manifest, stats = generate_manifest(archive_entries, detection_results, args.source_dir)

    # Write manifest
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for record in manifest:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # Write stats
    stats_path = Path(args.stats_output)
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    # Report
    status_dist = Counter(r.get("status", "?") for r in manifest)
    unique_bids = len(set(r["book_id"] for r in manifest))
    
    print(f"\n{'='*60}")
    print(f"Manifest generated: {len(manifest)} records")
    print(f"{'='*60}")
    print(f"Total entries:        {stats['total']}")
    print(f"Unique stems:         {stats['unique_stems']}")
    print(f"Duplicate stems:      {stats['duplicate_stems']}")
    print(f"Extra entries:        {stats['duplicate_entries']}")
    print(f"ID collisions fixed:  {stats['id_collisions_fixed']}")
    print(f"Unique book_id:       {unique_bids}")
    print(f"Missing detection:    {stats['missing_detection']}")
    print(f"Missing file:         {stats['missing_file']}")
    print(f"Status distribution:  {dict(status_dist)}")
    if stats['errors']:
        print(f"Errors:              {len(stats['errors'])}")

    print(f"\nOutput: {output_path}")
    print(f"Stats:  {stats_path}")

    # Validation
    assert len(manifest) == 1458, f"Expected 1458, got {len(manifest)}"
    assert unique_bids == 1458, f"Expected 1458 unique book_id, got {unique_bids}"
    assert status_dist.get("unknown", 0) == 0, f"Found {status_dist.get('unknown', 0)} unknown status"
    print(f"\n✓ Manifest validation PASSED")


if __name__ == "__main__":
    main()
