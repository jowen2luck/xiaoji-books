"""Diagnose: for duplicate stems, are detection statuses being collapsed?"""
import json
from pathlib import Path
from collections import Counter, defaultdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Load detection
detection_by_archive_id = {}
detection_by_file_path = {}
detection_by_stem = {}
with open(PROJECT_ROOT / "data/manifest-detection.jsonl", encoding="utf-8") as f:
    for line in f:
        r = json.loads(line.strip())
        aid = r.get("archive_id", "")
        fp = r.get("file_path", "")
        stem = r.get("stem", "")
        if aid:
            detection_by_archive_id[aid] = r
        if fp:
            detection_by_file_path[fp] = r
        if stem:
            # Count: only one survives
            detection_by_stem[stem] = r

print(f"detection by archive_id: {len(detection_by_archive_id)}")
print(f"detection by file_path: {len(detection_by_file_path)}")
print(f"detection by stem (collapsed): {len(detection_by_stem)}")

# Load archive-index
with open(PROJECT_ROOT / "data/archive-index.json", encoding="utf-8") as f:
    idx = json.load(f)
idx_pdfs = [ff for ff in idx["files"] if ff.get("type") == "pdf"]

# Load manifest
manifest = []
with open(PROJECT_ROOT / "data/manifest.jsonl", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            manifest.append(json.loads(line.strip()))

# Build manifest archive_id lookup
man_by_archive_id = {r["archive_id"]: r for r in manifest if r.get("archive_id")}

# For each detection, compare status via archive_id vs via stem-collapse
divergence_count = 0
divergent_examples = []
status_when_collapsed = Counter()
status_when_direct = Counter()

for archive_id, det_rec in detection_by_archive_id.items():
    stem = det_rec["stem"]
    status_via_archive = det_rec["status"]
    
    # What the collapsed stem dict gives
    stem_rec = detection_by_stem.get(stem)
    status_via_stem = stem_rec["status"] if stem_rec else "unknown"
    
    if status_via_archive != status_via_stem:
        divergence_count += 1
        status_when_collapsed[status_via_stem] += 1
        status_when_direct[status_via_archive] += 1
        if len(divergent_examples) < 10:
            divergent_examples.append({
                "archive_id": archive_id,
                "stem": stem,
                "status_via_archive": status_via_archive,
                "status_via_stem": status_via_stem,
                "stem_record_archive_id": stem_rec.get("archive_id") if stem_rec else None,
            })

print(f"\nDivergence (status differs by archive vs collapsed stem): {divergence_count}")
print(f"\nWhat collapsed stem dict gives (WRONG): {dict(status_when_collapsed)}")
print(f"What archive_id lookup gives (RIGHT): {dict(status_when_direct)}")

print(f"\nExamples of divergence:")
for ex in divergent_examples[:5]:
    print(f"  stem={ex['stem']} archive_status={ex['status_via_archive']} "
          f"collapsed_gives={ex['status_via_stem']} "
          f"(collapsed record is {ex['stem_record_archive_id']})")

# Now check: for each manifest entry, is its status correct?
manifest_correct = 0
manifest_wrong = 0
wrong_examples = []
for r in manifest:
    aid = r.get("archive_id", "")
    man_status = r.get("status", "")
    det_rec = detection_by_archive_id.get(aid)
    if det_rec:
        correct_status = det_rec["status"]
        if man_status == correct_status:
            manifest_correct += 1
        else:
            manifest_wrong += 1
            if len(wrong_examples) < 15:
                wrong_examples.append({
                    "book_id": r["book_id"],
                    "archive_id": aid,
                    "manifest_status": man_status,
                    "correct_status": correct_status,
                })
    else:
        manifest_wrong += 1

print(f"\nManifest status correctness:")
print(f"  Correct: {manifest_correct}/{len(manifest)}")
print(f"  Wrong:   {manifest_wrong}/{len(manifest)}")

print(f"\nWrong entries:")
for ex in wrong_examples:
    print(f"  {ex['book_id']} archive={ex['archive_id'].split('/')[-1]} manifest={ex['manifest_status']} should_be={ex['correct_status']}")

# Show stem collision detection: how does stem→archive_id mapping work?
stem_groups = defaultdict(list)
for archive_id, det in detection_by_archive_id.items():
    stem_groups[det["stem"]].append((archive_id, det["status"]))

collision_groups = {s: g for s, g in stem_groups.items() if len(g) > 1}
print(f"\nStems with duplicate archive_id groups: {len(collision_groups)}")
for stem, group in list(collision_groups.items())[:3]:
    statuses = Counter(x[1] for x in group)
    print(f"  stem={stem} ({len(group)} files): {dict(statuses)}")
