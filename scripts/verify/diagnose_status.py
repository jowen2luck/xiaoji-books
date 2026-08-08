"""Diagnose status mismatch between detection, archive-index, manifest."""
import json
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

det_path = PROJECT_ROOT / "data/manifest-detection.jsonl"
idx_path = PROJECT_ROOT / "data/archive-index.json"
manifest_path = PROJECT_ROOT / "data/manifest.jsonl"

# Load detection
det = {}
with open(det_path, encoding="utf-8") as f:
    for line in f:
        r = json.loads(line.strip())
        det[r["file_path"]] = r
print(f"Detection entries: {len(det)}")
print(f"Detection by status: {dict(Counter(r['status'] for r in det.values()))}")

# Load archive-index PDF files
with open(idx_path, encoding="utf-8") as f:
    idx = json.load(f)
idx_pdfs = [ff for ff in idx["files"] if ff.get("type") == "pdf"]
print(f"\narchive-index PDF files: {len(idx_pdfs)}")
archive_ids = [ff["id"] for ff in idx_pdfs]
print(f"archive_ids unique: {len(set(archive_ids))}")

# Examine id/path relationship
print(f"\nFirst 5 archive-index entries:")
for ff in idx_pdfs[:5]:
    print(f"  id={ff['id']}  path={ff['path']}  stem={ff['stem']}")

# Group by stem
stem_groups = {}
for ff in idx_pdfs:
    stem = ff["stem"]
    stem_groups.setdefault(stem, []).append(ff)
dup_stems = {s: g for s, g in stem_groups.items() if len(g) > 1}
print(f"\nDuplicate stems: {len(dup_stems)}")
for stem, group in list(dup_stems.items())[:3]:
    print(f"  {stem} ({len(group)} files):")
    for g in group:
        print(f"    id={g['id']}")

# Check detection lookup: file_path matches archive path format?
det_paths = set(det.keys())
idx_paths = set(ff["path"] for ff in idx_pdfs)
print(f"\nDetection paths: {len(det_paths)}")
print(f"archive paths: {len(idx_paths)}")
print(f"Intersection: {len(det_paths & idx_paths)}")
print(f"In detection but not archive: {len(det_paths - idx_paths)}")
print(f"In archive but not detection: {len(idx_paths - det_paths)}")

# Sample mismatches
if det_paths - idx_paths:
    print(f"\nSample detection-only paths:")
    for p in list(det_paths - idx_paths)[:5]:
        print(f"  {p}")
if idx_paths - det_paths:
    print(f"\nSample archive-only paths:")
    for p in list(idx_paths - det_paths)[:5]:
        print(f"  {p}")

# Load manifest
mf = []
with open(manifest_path, encoding="utf-8") as f:
    for line in f:
        if line.strip():
            mf.append(json.loads(line.strip()))
print(f"\nManifest entries: {len(mf)}")
print(f"Manifest by status: {dict(Counter(r.get('status') for r in mf))}")

# Check archive_ids in manifest
mf_with_archive_id = sum(1 for r in mf if r.get("source_archive_id"))
print(f"Manifest with source_archive_id: {mf_with_archive_id}")

# Check: do manifest entries match archive-index by source_full_path?
mf_paths = set(r.get("source_full_path", "") for r in mf)
mf_paths.update(r.get("source_path", "") for r in mf if r.get("source_path"))
print(f"\nManifest paths (unique): {len(mf_paths)}")
print(f"Manifest ∩ archive paths: {len(mf_paths & idx_paths)}")

# Manifest path samples
print(f"\nFirst 5 manifest source_paths:")
for r in mf[:5]:
    print(f"  book={r['book_id']} status={r['status']} path={r.get('source_full_path','') or r.get('source_path','')}")
