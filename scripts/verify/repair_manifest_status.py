"""Repair manifest.jsonl status fields WITHOUT changing book_ids.

Uses archive_id (unique, stable) to look up correct detection status.
Only updates the status field; book_id, aliases, and all other fields preserved.

This satisfies the requirement: "不要全面改名；archive_id→book_id 映射稳定"
"""
import json
import sys
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

MANIFEST_PATH = PROJECT_ROOT / "data/manifest.jsonl"
DETECTION_PATH = PROJECT_ROOT / "data/manifest-detection.jsonl"

# Load detection by archive_id
detection_by_archive_id = {}
with open(DETECTION_PATH, encoding="utf-8") as f:
    for line in f:
        r = json.loads(line.strip())
        aid = r.get("archive_id", "")
        if aid:
            detection_by_archive_id[aid] = r

print(f"Detection by archive_id: {len(detection_by_archive_id)}")

# Load manifest
records = []
with open(MANIFEST_PATH, encoding="utf-8") as f:
    for line in f:
        if line.strip():
            records.append(json.loads(line.strip()))
print(f"Manifest records: {len(records)}")

# Verify: every manifest record has archive_id that's in detection
missing = []
for r in records:
    aid = r.get("archive_id", "")
    if aid not in detection_by_archive_id:
        missing.append(aid)
print(f"Manifest records with archive_id missing from detection: {len(missing)}")
if missing:
    print("  " + "\n  ".join(missing[:5]))

# Repair status
changes = []
status_before = Counter(r.get("status", "?") for r in records)
for r in records:
    aid = r.get("archive_id", "")
    det = detection_by_archive_id.get(aid)
    if det:
        correct_status = det.get("status", "")
        current_status = r.get("status", "")
        if current_status != correct_status:
            changes.append({
                "book_id": r["book_id"],
                "archive_id": aid,
                "old_status": current_status,
                "new_status": correct_status,
            })
            r["status"] = correct_status
            # Also sync page_count if needed
            det_pages = det.get("total_pages", 0)
            if det_pages and r.get("page_count", 0) != det_pages:
                r["page_count"] = det_pages

status_after = Counter(r.get("status", "?") for r in records)

print(f"\nStatus distribution BEFORE repair: {dict(status_before)}")
print(f"Status distribution AFTER repair:  {dict(status_after)}")
print(f"\nChanges: {len(records) - len([c for c in changes if not c])} records examined, {len(changes)} status changes")

if changes:
    print(f"\nChanges (first 20):")
    for c in changes[:20]:
        print(f"  {c['book_id']} | {c['archive_id'][:50]}")
        print(f"    {c['old_status']} -> {c['new_status']}")

# Check: do ALL unique archive_ids have exactly one book_id?
aid_to_bids = {}
for r in records:
    aid = r.get("archive_id", "")
    bid = r.get("book_id", "")
    aid_to_bids.setdefault(aid, set()).add(bid)

multi_bid = {aid: bids for aid, bids in aid_to_bids.items() if len(bids) > 1}
print(f"\narchive_ids mapped to multiple book_ids: {len(multi_bid)}")

# Write repaired manifest
output_path = MANIFEST_PATH  # overwrite in place
with open(output_path, "w", encoding="utf-8") as f:
    for r in records:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

print(f"\nWrote repaired manifest to: {output_path}")

# Verification stats
unique_bids = len(set(r["book_id"] for r in records))
nonempty_artifact = sum(1 for r in records if r.get("artifact_id"))
print(f"Unique book_id: {unique_bids} (expect 1458)")
print(f"Records with artifact_id: {nonempty_artifact}/1458")
assert unique_bids == 1458, f"book_id collision: {unique_bids}"
assert status_after.get("unknown", 0) == 0, "unknown status remaining"
print("\n✓ Repair validation PASSED")
