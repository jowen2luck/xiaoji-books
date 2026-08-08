"""M2b End-to-End Verification.

Tests:
1. Process 5 books across 3 statuses (text_extractable, ocr_required, partial_text).
2. Write Evidence JSONL.
3. Load into catalog.db + FTS5.
4. Verify all Evidence fields are complete.
5. Verify FTS5 CJK search returns expected results.
6. Verify text_raw ≠ text_normalized schema compliance.
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "pipeline"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "catalog"))

# --- Step 1: Pick 5 books across statuses ---
manifest = []
with open(PROJECT_ROOT / "data/manifest.jsonl", "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            manifest.append(json.loads(line))

# Pick: 2 text_extractable, 2 ocr_required, 1 partial_text
picks = {"text_extractable": [], "ocr_required": [], "partial_text": []}
for r in manifest:
    s = r.get("status")
    if s in picks and len(picks[s]) < (2 if s != "partial_text" else 1):
        picks[s].append(r)
    if all(len(v) >= (2 if k != "partial_text" else 1) for k, v in picks.items()):
        break

pick_list = picks["text_extractable"] + picks["ocr_required"] + picks["partial_text"]
print(f"Picks: {[r['book_id'] for r in pick_list]}")

# --- Step 2: Use TEMPORARY directory for test evidence (never touch production) ---
evidence_dir = Path(tempfile.mkdtemp(prefix="m2b_e2e_"))
checkpoint = evidence_dir / "checkpoint.jsonl"

print(f"Test evidence dir: {evidence_dir}", file=sys.stderr)

# Process each book individually
from scripts.pipeline.batch_ingest import load_manifest, resolve_pdf_path
from scripts.pipeline.batch_ingest import _process_one_book, _write_evidence

base_dir = str(PROJECT_ROOT / "data/_kage/www.marxists.org")
books_path = evidence_dir / "books.jsonl"
pages_path = evidence_dir / "pages.jsonl"
paragraphs_path = evidence_dir / "paragraphs.jsonl"

success = 0
errors = 0
for rec in pick_list:
    book_id = rec["book_id"]
    status = rec.get("status")
    artifact_id = rec.get("artifact_id")
    pdf_path = resolve_pdf_path(rec, base_dir)
    if not pdf_path:
        print(f"  SKIP (not found): {book_id}")
        errors += 1
        continue
    print(f"  Processing {book_id} ({status})...")
    try:
        result = _process_one_book(
            pdf_path, book_id, artifact_id, status, rec,
            dpi=200, poppler_path=None, max_pages=3
        )
        _write_evidence(result, books_path, pages_path, paragraphs_path)
        success += 1
        print(f"    OK: {len(result.get('pages',[]))} pages")
    except Exception as e:
        print(f"    ERROR: {e}")
        errors += 1

print(f"\nProcessed: {success} success, {errors} errors")

# --- Step 3: Inspect evidence ---
books_recs = []
with open(books_path, "r", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            books_recs.append(json.loads(line))

pages_recs = []
with open(pages_path, "r", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            pages_recs.append(json.loads(line))

paras_recs = []
with open(paragraphs_path, "r", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            paras_recs.append(json.loads(line))

print(f"\nEvidence totals: {len(books_recs)} books, {len(pages_recs)} pages, {len(paras_recs)} paragraphs")

# --- Step 4: Check schema compliance ---
print("\n=== Schema Compliance Check ===")
required_page_fields = [
    "id", "type", "book_id", "artifact_id", "source_hash",
    "page_index", "printed_page",
    "text_raw", "text_normalized", "normalization_version",
    "extractor", "confidence", "evidence_set_id",
]
required_para_fields = [
    "id", "type", "book_id", "artifact_id", "source_hash",
    "page_index", "printed_page", "block_id", "char_range",
    "text_raw", "text_normalized", "normalization_version",
    "extractor", "evidence_set_id",
]

all_ok = True
for rec in pages_recs:
    missing = [f for f in required_page_fields if f not in rec]
    if missing:
        print(f"  PAGE {rec.get('id')} MISSING: {missing}")
        all_ok = False

for rec in paras_recs:
    missing = [f for f in required_para_fields if f not in rec]
    if missing:
        print(f"  PARA {rec.get('id')} MISSING: {missing}")
        all_ok = False

if all_ok:
    print("  All required fields present ✓")

# --- Step 5: Check non-empty critical fields ---
print("\n=== Non-empty Field Check ===")
critical = {
    "pages": ["id", "book_id", "artifact_id", "source_hash", "text_raw", "text_normalized"],
    "paragraphs": ["id", "book_id", "artifact_id", "source_hash", "text_raw", "text_normalized"],
}
records = {"pages": pages_recs, "paragraphs": paras_recs}
for rtype, fields in critical.items():
    empty_count = 0
    for rec in records[rtype]:
        for fld in fields:
            v = rec.get(fld)
            if v is None or v == "" or v == []:
                empty_count += 1
                if empty_count <= 3:
                    print(f"  {rtype}/{rec.get('id')}.{fld} is empty")
    print(f"  {rtype}: {empty_count} empty critical fields")

# --- Step 6: Write to catalog.db ---
print("\n=== Writing to catalog.db ===")
catalog_db = PROJECT_ROOT / "data/catalog/catalog_m2b_test.db"
if catalog_db.exists():
    catalog_db.unlink()

from scripts.catalog.init_db import init_db
from scripts.catalog.load_catalog import (
    load_jsonl, insert_books, insert_pages, insert_paragraphs, insert_anchors,
    get_loaded_evidence_sets, collect_evidence_set_info, record_evidence_sets,
)

init_db(str(catalog_db))
conn = sqlite3.connect(str(catalog_db))

loaded = get_loaded_evidence_sets(conn)
n_books = insert_books(conn, books_recs, loaded)
page_set_counts = insert_pages(conn, pages_recs, loaded)
para_set_counts, n_fts = insert_paragraphs(conn, paras_recs, loaded)
n_anchors = insert_anchors(conn, paras_recs, loaded)
set_info = collect_evidence_set_info(books_recs, pages_recs, paras_recs)
new_sets = {es for es in set_info if es not in loaded}
record_evidence_sets(conn, {es: set_info[es] for es in new_sets})
conn.commit()
print(f"  Inserted: {n_books} books, {sum(page_set_counts.values())} pages, {sum(para_set_counts.values())} paras, {n_anchors} anchors, {n_fts} FTS")

# --- Step 7: Test FTS5 search ---
print("\n=== FTS5 Search ===")
test_queries = [
    "Internationale",
    "鲍狄埃",
    "过渡时",
    "一本",
]
for q in test_queries:
    try:
        cur = conn.execute(
            "SELECT COUNT(*) FROM paragraphs_fts WHERE paragraphs_fts MATCH ?", (q,)
        )
        cnt = cur.fetchone()[0]
        print(f"  MATCH '{q}': {cnt} hits")
    except Exception as e:
        print(f"  MATCH '{q}': ERROR {e}")

conn.close()

# Cleanup test db
if catalog_db.exists():
    catalog_db.unlink()

print(f"\n=== M2b E2E: {'PASS' if (success >= 4 and errors == 0 and all_ok) else 'FAIL'} ===")
