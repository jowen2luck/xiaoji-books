"""Quick smoke test for the fitz → pdfplumber → OCR pipeline."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.pipeline.text_extract import extract_pdf_text

SAMPLES = [
    ("data/_kage/www.marxists.org/chinese/marx/capital/01.pdf", "test_capital_01"),
    ("data/_kage/www.marxists.org/chinese/engels/index.htm", None),
]

# Find first existing PDF
test_pdf = None
for p, _ in SAMPLES:
    if p and p.endswith(".pdf") and Path(p).exists():
        test_pdf = p
        break

if not test_pdf:
    # Fallback: find any text_extractable PDF
    for pdf in Path("data/_kage").rglob("*.pdf"):
        test_pdf = str(pdf)
        break

if not test_pdf:
    print("No PDF found for smoke test")
    sys.exit(0)

print(f"Testing: {test_pdf}")
t0 = time.time()
r = extract_pdf_text(test_pdf, "smoke_test_book", "text_extractable", max_pages=10)
dt = time.time() - t0

print(f"Pages: {r['processed_pages']}, texts: {r['metadata']['text_extractable_pages']}, ocr: {r['metadata']['ocr_pages']}, time: {dt:.1f}s")
if r['pages']:
    p0 = r['pages'][0]
    print(f"  Page 1: extractor={p0['extractor']} lens={len(p0['text_raw'])}")
    print(f"  Page 1 text: {p0['text_normalized'][:200]!r}")
print("OK" if r['processed_pages'] > 0 else "NO PAGES")
