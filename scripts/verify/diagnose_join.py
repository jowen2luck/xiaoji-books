"""Diagnose the path format difference between detection and archive-index."""
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Detection paths: data\_kage\www.marxists.org\chinese\...
# Archive-index paths: chinese\...

# Load sample
with open(PROJECT_ROOT / "data/manifest-detection.jsonl", encoding="utf-8") as f:
    det = [json.loads(line.strip()) for line in f if line.strip()]

with open(PROJECT_ROOT / "data/archive-index.json", encoding="utf-8") as f:
    idx = json.load(f)

idx_pdfs = [ff for ff in idx["files"] if ff.get("type") == "pdf"]

# Try to join: strip "data\_kage\www.marxists.org\" prefix from detection
print(f"Sample det paths:")
for d in det[:5]:
    print(f"  {d['file_path']}")

print(f"\nSample archive paths:")
for ff in idx_pdfs[:5]:
    print(f"  {ff['path']}")

# Mapping: does archive path appear as suffix of detection path?
det_by_suffix = {}
for d in det:
    fp = d["file_path"]
    # Use just the filename as key
    fname = fp.replace("\\", "/").split("/")[-1]
    det_by_suffix.setdefault(fp.replace("\\", "/"), d)

# Try: archive path uses backslash; convert to forward slash
archive_relpaths = set()
for ff in idx_pdfs:
    archive_relpaths.add(ff["path"].replace("\\", "/"))

det_relpaths = set()
for d in det:
    det_relpaths.add(d["file_path"].replace("\\", "/"))

# Detection has "data/_kage/www.marxists.org/" prefix; archive doesn't
det_stripped = set()
PREFIX = "data/_kage/www.marxists.org/"
for dp in det_relpaths:
    if dp.startswith(PREFIX):
        det_stripped.add(dp[len(PREFIX):])
    else:
        det_stripped.add(dp)

print(f"\nArchive relpaths: {len(archive_relpaths)}")
print(f"Detection relpaths (stripped): {len(det_stripped)}")
print(f"Intersection: {len(det_stripped & archive_relpaths)}")

if det_stripped & archive_relpaths:
    print(f"Joinable: {(det_stripped & archive_relpaths).__iter__().__next__()}")
else:
    print("No direct match. Checking substrings...")
    sample = list(archive_relpaths)[:3]
    for s in sample:
        matches = [d for d in list(det_stripped)[:100] if s.split("/")[-1] == d.split("/")[-1]]
        print(f"  archive {s!r} → found {len(matches)} filename matches in detection")
