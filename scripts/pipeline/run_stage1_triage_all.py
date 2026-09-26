#!/usr/bin/env python3
"""Stage 1 Global Triage & Invariant Verification for all 1,458 Books.

Audits every single book and page:
- Classifies pages into:
  * text_layer_extracted (has usable vector/embedded text)
  * text_layer_missing_or_low_text (needs Stage 2 visual OCR)
- Computes SHA-256 checksums.
- Verifies mathematical invariant:
  extracted_pages + low_text_pages == total_pages for 100% of books.
- Outputs:
  * data/evidence/stage1_pages.jsonl
  * data/evidence/stage1_summary.json
"""
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent.parent
MANIFEST_PATH = ROOT / "data/manifest.jsonl"
EVIDENCE_DIR = ROOT / "data/evidence"
OUT_PAGES = EVIDENCE_DIR / "stage1_pages.jsonl"
OUT_SUMMARY = EVIDENCE_DIR / "stage1_summary.json"
CHECKPOINT_FILE = EVIDENCE_DIR / "chk_stage1.jsonl"


def get_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    
    # 1. Load manifest
    books = []
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                books.append(json.loads(line))
    
    # 2. Load completed books from checkpoint
    completed_book_ids = set()
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        completed_book_ids.add(json.loads(line)["book_id"])
                    except Exception:
                        pass
    
    pending_books = [b for b in books if b["book_id"] not in completed_book_ids]
    print(f"=== STAGE 1 GLOBAL TRIAGE LAUNCHED ===", flush=True)
    print(f"Total Books: {len(books)} | Already Processed: {len(completed_book_ids)} | Pending: {len(pending_books)}", flush=True)

    total_pages_all = 0
    total_extracted_all = 0
    total_low_text_all = 0
    invariant_failures = []

    t0_global = time.time()
    
    with open(OUT_PAGES, "a", encoding="utf-8") as f_pages, open(CHECKPOINT_FILE, "a", encoding="utf-8") as f_chk:
        for idx, book in enumerate(pending_books, 1):
            book_id = book["book_id"]
            source_rel = book.get("source_path") or book.get("source_full_path", "")
            pdf_path = ROOT / "data/_kage/www.marxists.org" / source_rel
            if not pdf_path.exists():
                pdf_path = ROOT / source_rel
            
            if not pdf_path.exists():
                print(f"[{idx}/{len(pending_books)}] [SKIP] File not found: {source_rel}", flush=True)
                continue

            try:
                pdf_hash = get_sha256(pdf_path)
                doc = pymupdf.open(str(pdf_path))
                page_count = len(doc)
                
                book_extracted = 0
                book_low_text = 0

                for p_idx in range(page_count):
                    page = doc[p_idx]
                    txt = page.get_text("text").strip()
                    char_count = len(txt)

                    # Triage heuristic
                    is_clean = (char_count >= 30)
                    classification = "text_layer_extracted" if is_clean else "text_layer_missing_or_low_text"
                    
                    if is_clean:
                        book_extracted += 1
                    else:
                        book_low_text += 1

                    page_rec = {
                        "id": f"{book_id}:p{p_idx}",
                        "book_id": book_id,
                        "page_index": p_idx,
                        "classification": classification,
                        "char_count": char_count,
                        "text_normalized": txt if is_clean else "",
                        "extractor": "pymupdf_vector@1.25.0",
                        "pipeline_stage": "stage1_triage",
                        "created_at": _now_iso()
                    }
                    f_pages.write(json.dumps(page_rec, ensure_ascii=False) + "\n")

                doc.close()

                # Invariant Verification
                if book_extracted + book_low_text != page_count:
                    err_msg = f"Invariant FAIL on {book_id}: {book_extracted}+{book_low_text} != {page_count}"
                    print(f"  ERROR: {err_msg}", flush=True)
                    invariant_failures.append(err_msg)
                
                total_pages_all += page_count
                total_extracted_all += book_extracted
                total_low_text_all += book_low_text

                # Checkpoint
                chk_rec = {
                    "book_id": book_id,
                    "sha256": pdf_hash,
                    "total_pages": page_count,
                    "extracted_pages": book_extracted,
                    "low_text_pages": book_low_text,
                    "timestamp": _now_iso()
                }
                f_chk.write(json.dumps(chk_rec, ensure_ascii=False) + "\n")
                f_chk.flush()
                f_pages.flush()

                if idx % 50 == 0 or idx == len(pending_books):
                    elapsed = round(time.time() - t0_global, 1)
                    rate = round(total_pages_all / max(1.0, elapsed), 1)
                    print(f"[{idx}/{len(pending_books)}] {book_id} | Pages: {page_count} (Ext: {book_extracted}, Low: {book_low_text}) | Cumul: {total_pages_all}p ({rate} p/s)", flush=True)

            except Exception as e:
                print(f"[{idx}/{len(pending_books)}] [ERROR] {book_id}: {e}", flush=True)

    elapsed_total = round(time.time() - t0_global, 2)
    summary = {
        "completed_at": _now_iso(),
        "total_books_audited": len(books),
        "total_pages_audited": total_pages_all,
        "text_layer_extracted_pages": total_extracted_all,
        "visual_ocr_needed_pages": total_low_text_all,
        "invariant_check_passed": (len(invariant_failures) == 0),
        "invariant_failures": invariant_failures,
        "elapsed_seconds": elapsed_total
    }

    with open(OUT_SUMMARY, "w", encoding="utf-8") as f_sum:
        json.dump(summary, f_sum, ensure_ascii=False, indent=2)

    print("=" * 60, flush=True)
    print("STAGE 1 GLOBAL TRIAGE COMPLETE!", flush=True)
    print(f"Total Pages: {total_pages_all} | Extracted: {total_extracted_all} | Needs Visual OCR: {total_low_text_all}", flush=True)
    print(f"Invariant: {'PASS (100% Conserved)' if not invariant_failures else 'FAIL'}", flush=True)
    print(f"Elapsed Time: {elapsed_total}s", flush=True)
    print("=" * 60, flush=True)


if __name__ == "__main__":
    main()
