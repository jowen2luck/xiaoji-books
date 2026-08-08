"""Pick 3 PDFs for M2a smoke test: 2 ocr_required + 1 partial_text."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

MANIFEST = "data/manifest.jsonl"

scan_files = []
partial_files = []

with open(MANIFEST, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        st = rec.get("status", "")
        sp = rec.get("source_path", "")
        if st == "ocr_required":
            scan_files.append(sp)
        elif st == "partial_text":
            partial_files.append(sp)

# Pick 2 ocr_required (smallish ones, < 5MB) and 1 partial_text
scan_small = [p for p in scan_files if Path("data/_kage/www.marxists.org", p).exists() and Path("data/_kage/www.marxists.org", p).stat().st_size < 5 * 1024 * 1024]
partial_small = [p for p in partial_files if Path("data/_kage/www.marxists.org", p).exists() and Path("data/_kage/www.marxists.org", p).stat().st_size < 5 * 1024 * 1024]

print(f"Total ocr_required: {len(scan_files)}")
print(f"Total partial_text: {len(partial_files)}")
print(f"Small ocr_required (<5MB): {len(scan_small)}")
print(f"Small partial_text (<5MB): {len(partial_small)}")

picks = []
if len(scan_small) >= 2:
    picks.extend(scan_small[:2])
else:
    picks.extend(scan_files[:2])

if len(partial_small) >= 1:
    picks.append(partial_small[0])
else:
    picks.append(partial_files[0])

print("\nSmoke test picks:")
for p in picks:
    full = Path("data/_kage/www.marxists.org", p)
    size_mb = full.stat().st_size / 1024 / 1024 if full.exists() else 0
    print(f"  {p} ({size_mb:.1f}MB)")

# Write picks to file
with open("data/smoke_picks.json", "w", encoding="utf-8") as f:
    json.dump(picks, f, ensure_ascii=False, indent=2)
print("\nWrote to data/smoke_picks.json")
