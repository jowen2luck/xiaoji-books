"""M2a Smoke Test Verification — confirm 3 OCR outputs are valid.

Checks:
1. All 3 smoke output JSON files exist
2. Each has non-empty pages with OCR text
3. Average confidence > 0.80
4. No encoding errors (text contains CJK characters)
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

CASES = [
    ("poem_of_pottier.pdf", "ocr_required", "data/evidence/ocr_smoke_output.json"),
    ("pottier_bio1.pdf", "ocr_required", "data/evidence/ocr_smoke_pottier_bio1.json"),
    ("053103.pdf", "partial_text", "data/evidence/ocr_smoke_053103.json"),
]

CJK_PATTERN = re.compile(r'[\u4e00-\u9fff]')

print("=" * 60)
print("M2a Smoke Test Verification")
print("=" * 60)

all_pass = True
for name, status, out_path in CASES:
    full_path = PROJECT_ROOT / out_path
    print(f"\n[{status}] {name}")
    
    if not full_path.exists():
        print(f"  FAIL: output file not found: {out_path}")
        all_pass = False
        continue
    
    with open(full_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    pages = data.get("pages", [])
    if not pages:
        print(f"  FAIL: no pages in output")
        all_pass = False
        continue
    
    page_count = len(pages)
    total_blocks = sum(p.get("block_count", 0) for p in pages)
    avg_conf = sum(p.get("avg_confidence", 0) for p in pages) / page_count if page_count else 0
    
    # Check CJK presence
    all_text = " ".join(
        b.get("text", "")
        for p in pages
        for b in p.get("blocks", [])
    )
    has_cjk = bool(CJK_PATTERN.search(all_text))
    
    print(f"  Pages: {page_count}, Blocks: {total_blocks}")
    print(f"  Avg confidence: {avg_conf:.3f}")
    print(f"  CJK detected: {has_cjk}")
    print(f"  Sample: {all_text[:50]}...")
    
    if avg_conf >= 0.80 and has_cjk:
        print(f"  → PASS")
    else:
        print(f"  → FAIL (conf < 0.80 or no CJK)")
        all_pass = False

print(f"\n{'=' * 60}")
print(f"Overall: {'PASS' if all_pass else 'FAIL'}")
