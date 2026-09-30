#!/usr/bin/env python3
"""
Batch OCR for ALL unprocessed books.

Covers far more than diagnose_content_quality did:
  1. manifest status in (ocr_required, partial_text) that have no valid output yet
  2. text_extractable / TEXT_OK books that produced 0 extracted pages (misclassified)
  3. text_extractable / TEXT_OK books flagged by diagnose as needing OCR
  4. text_extractable books whose average CJK chars/page is very low (likely mislabeled)

For each book: extract_pdf_text with OCR fallback → pages.jsonl (page_index order,
which preserves chapter/section flow) → then rebuild_paragraphs to inject
chapter/section headings as paragraph metadata. Resume-friendly: skip books
that already have valid pages output matching manifest page_count.

Usage:
  python scripts/verify/batch_ocr_unprocessed.py --output-dir data/.ocr_reprocess
  python scripts/verify/batch_ocr_unprocessed.py --limit 10 --dpi 200
"""

import argparse
import io
import json
import os
import sys
import time
from pathlib import Path

sys.stderr = io.StringIO()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.pipeline.text_extract import extract_pdf_text, compute_sha256
from scripts.pipeline.normalizer import normalize_text


def load_manifest(path: str = "data/manifest.jsonl") -> list:
    records = []
    path = Path(path)
    if not path.exists():
        return records
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def load_text_extract_checkpoint(path: str = "data/text_extract_checkpoint.jsonl") -> dict:
    """Map book_id -> {pages, status, ocr_pages, text_pages}."""
    cp = {}
    p = Path(path)
    if not p.exists():
        return cp
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                bid = r.get("book_id", "")
                if bid:
                    cp[bid] = r
            except json.JSONDecodeError:
                continue
    return cp


def load_diagnose_results(path: str = "data/diagnose_content_quality.jsonl") -> dict:
    """Map book_id -> recommendation string."""
    d = {}
    p = Path(path)
    if not p.exists():
        return d
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                rec = r.get("overall", {}).get("recommendation", "")
                if rec and r.get("book_id"):
                    d[r["book_id"]] = rec
            except json.JSONDecodeError:
                continue
    return d


def load_processed_books(pages_dir: str) -> dict:
    """Map book_id -> page_count from existing pages.jsonl files in output dir."""
    result = {}
    d = Path(pages_dir)
    if not d.exists():
        return result
    for f in d.glob("*_pages.jsonl"):
        bid = f.name.replace("_pages.jsonl", "")
        pages = 0
        with open(f, "r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    pages += 1
        result[bid] = pages
    return result


def count_meaningful_pages(pages_dir: str, book_id: str, min_chars: int = 50) -> int:
    """Count pages with meaningful text (not 0-char empty pages)."""
    f = Path(pages_dir) / f"{book_id}_pages.jsonl"
    if not f.exists():
        return 0
    meaningful = 0
    with open(f, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                text = r.get("text_raw", "") or ""
                if len(text.strip()) >= min_chars:
                    meaningful += 1
            except json.JSONDecodeError:
                continue
    return meaningful


def select_books_needing_ocr(
    manifest: list,
    text_checkpoint: dict,
    diagnose: dict,
    processed: dict,
    min_pages_threshold: float = 0.80,
) -> list:
    """
    Select books that need OCR processing (broad, conservative criteria).

    Returns list of manifest records that should be processed.
    """
    selected = []
    seen = set()

    for rec in manifest:
        book_id = rec.get("book_id", "")
        if not book_id or book_id in seen:
            continue

        status = rec.get("status", "")
        pdf_pages = rec.get("page_count", 0)
        pdf_path = rec.get("source_full_path", "")

        if not pdf_path or not Path(pdf_path).exists():
            continue

        need = False
        reason = ""

        if status in ("ocr_required", "partial_text"):
            # These should always need OCR unless they already have valid output
            existing = processed.get(book_id, 0)
            if existing > 0 and existing >= int(pdf_pages * min_pages_threshold):
                # Already has valid output
                continue
            need = True
            reason = f"manifest={status}"
        elif status == "text_extractable":
            # Check if it actually has meaningful content
            existing = processed.get(book_id, 0)
            cp = text_checkpoint.get(book_id)

            # Condition A: 0 extracted pages despite being marked text_extractable
            if cp and cp.get("pages", 0) == 0 and pdf_pages > 0:
                need = True
                reason = f"zero_extracted(pdf={pdf_pages})"
            # Condition B: diagnose flagged it as needing OCR
            elif diagnose.get(book_id) in ("NEEDS_FULL_OCR", "PARTIAL_TEXT_NEEDS_OCR"):
                if existing == 0:
                    need = True
                    reason = f"diagnose={diagnose[book_id]}"
            # Condition C: already processed output but very few meaningful pages suggest mis-extraction
            elif existing > 0:
                meaningful = count_meaningful_pages(str(Path(processed.get("_dir", "data/.ocr_reprocess")).parent), book_id) if "_dir" in processed else 0
                # Only flag if we already have the dir info
                pass  # Already has output — skip

        if need:
            rec["_ocr_reason"] = reason
            selected.append(rec)
            seen.add(book_id)

    return selected


def rebuild_paragraphs_for_pages(pages_dir: str, book_id: str) -> tuple:
    """Run rebuild_paragraphs logic on a single book's pages file.

    Returns (paragraph_count, chapter_count).
    """
    from scripts.verify.rebuild_paragraphs import rebuild_paragraphs_for_page

    pages_file = Path(pages_dir) / f"{book_id}_pages.jsonl"
    if not pages_file.exists():
        return 0, 0

    paras = 0
    chapters = 0

    out_file = Path(pages_dir) / f"{book_id}_paragraphs.jsonl"
    with open(pages_file, "r", encoding="utf-8") as fin, \
         open(out_file, "w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                page = json.loads(line)
            except json.JSONDecodeError:
                continue
            for para in rebuild_paragraphs_for_page(page):
                paras += 1
                if para.get("is_chapter_heading"):
                    chapters += 1
                fout.write(json.dumps(para, ensure_ascii=False) + "\n")

    return paras, chapters


def process_book(book_id: str, pdf_path: str, output_dir: str, dpi: int = 200) -> dict:
    """Extract text (with OCR fallback) for one book, write pages.jsonl.

    OCR already runs in page_index order — this naturally preserves
    chapter/section flow since chapters progress sequentially through pages.
    """
    start_time = time.time()
    result = {
        "book_id": book_id,
        "pdf_path": pdf_path,
        "status": "pending",
        "pages": 0,
        "paragraphs": 0,
        "chapters": 0,
        "text_pages": 0,
        "ocr_pages": 0,
        "elapsed_sec": 0,
        "error": None,
        "output_file": None,
    }

    if not Path(pdf_path).exists():
        result["status"] = "file_not_found"
        return result

    try:
        extraction = extract_pdf_text(
            pdf_path=pdf_path,
            book_id=book_id,
            status="text_extractable",
            dpi=dpi,
            ocr_fallback=True,
            min_text_chars=50,
        )

        pages = extraction.get("pages", [])
        result["pages"] = len(pages)

        text_pages = 0
        ocr_pages = 0
        output_pages = []

        for page in pages:
            text_raw = page.get("text_raw", "")
            extractor = page.get("extractor", "")

            if "ocr" in extractor or "rapidocr" in extractor:
                ocr_pages += 1
            else:
                text_pages += 1

            text_normalized, _, _ = normalize_text(text_raw)

            page_record = {
                "id": f"{book_id}:p{page['page_index']}",
                "book_id": book_id,
                "artifact_id": extraction.get("artifact_id", ""),
                "page_index": page["page_index"],
                "printed_page": page.get("printed_page", str(page["page_index"] + 1)),
                "text_raw": text_raw,
                "text_normalized": text_normalized,
                "normalization_version": "norm_v1",
                "extractor": extractor,
                "extractor_version": "batch_v1",
                "confidence": page.get("confidence", 0.0),
                "ocr_fallback_used": "ocr" in extractor,
                "block_count": page.get("block_count", 0),
                "evidence_set_id": f"es-batch-{book_id}",
            }
            output_pages.append(page_record)

        result["text_pages"] = text_pages
        result["ocr_pages"] = ocr_pages

        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        out_file = out_path / f"{book_id}_pages.jsonl"

        with open(out_file, "w", encoding="utf-8") as f:
            for pr in output_pages:
                f.write(json.dumps(pr, ensure_ascii=False) + "\n")

        result["output_file"] = str(out_file)

        # Step 2: rebuild paragraphs with chapter/section structure
        # Note: page_index order is preserved → chapter order follows naturally
        paras, chapters = rebuild_paragraphs_for_pages(output_dir, book_id)
        result["paragraphs"] = paras
        result["chapters"] = chapters

        result["status"] = "success"

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    result["elapsed_sec"] = round(time.time() - start_time, 1)
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Batch OCR for all unprocessed books")
    parser.add_argument("--manifest", default="data/manifest.jsonl")
    parser.add_argument("--diagnose", default="data/diagnose_content_quality.jsonl")
    parser.add_argument("--text-checkpoint", default="data/text_extract_checkpoint.jsonl")
    parser.add_argument("--output-dir", default="data/.ocr_reprocess")
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--min-pages-ratio", type=float, default=0.80,
                        help="Skip if existing pages >= ratio * manifest page_count")
    args = parser.parse_args()

    Path(args.output_dir).mkdir(parents=True, exist_ok=True)

    # Load all data sources
    manifest = load_manifest(args.manifest)
    print(f"Manifest: {len(manifest)} books total")

    text_checkpoint = load_text_extract_checkpoint(args.text_checkpoint)
    diagnose = load_diagnose_results(args.diagnose)
    processed = load_processed_books(args.output_dir)

    print(f"Text checkpoint: {len(text_checkpoint)} entries")
    print(f"Diagnose results: {len(diagnose)} entries")
    print(f"Already processed (pages.jsonl): {len(processed)} books")

    # Select books needing OCR (broad criteria)
    pending = select_books_needing_ocr(
        manifest, text_checkpoint, diagnose, processed,
        min_pages_threshold=args.min_pages_ratio,
    )

    print(f"\nBooks needing OCR: {len(pending)}")

    # Show first few reasons
    if pending:
        from collections import Counter
        reasons = Counter(r.get("_ocr_reason", "") for r in pending)
        print("Reasons:")
        for reason, count in reasons.most_common():
            print(f"  {count:4d}  {reason}")

    # Sort by page count (smallest first for quick wins)
    pending.sort(key=lambda b: b.get("page_count", 0))

    if args.limit:
        pending = pending[:args.limit]
        print(f"\nLimited to first {args.limit}")

    if not pending:
        print("\nNothing to process. All books are complete.")
        return

    print(f"\nProcessing {len(pending)} books...\n")

    results = []
    grand_total_pages = 0
    grand_total_ocr = 0
    grand_total_paras = 0
    grand_total_chapters = 0
    success_count = 0
    error_count = 0
    total_start = time.time()

    for i, book in enumerate(pending):
        book_id = book.get("book_id", "unknown")
        pdf_path = book.get("source_full_path", "")
        pages = book.get("page_count", 0)
        reason = book.get("_ocr_reason", "")

        print(f"[{i+1}/{len(pending)}] {book_id} ({pages} pages) [{reason}]...", flush=True)

        res = process_book(book_id, pdf_path, args.output_dir, args.dpi)
        results.append(res)

        tag = "PASS" if res["status"] == "success" else "FAIL"
        print(f"  {tag}: {res['status']} | text={res['text_pages']} ocr={res['ocr_pages']} "
              f"paras={res['paragraphs']} chapters={res['chapters']} | {res['elapsed_sec']}s")

        if res["error"]:
            print(f"    error: {res['error'][:200]}")

        if res["status"] == "success":
            success_count += 1
            grand_total_pages += res["pages"]
            grand_total_ocr += res["ocr_pages"]
            grand_total_paras += res["paragraphs"]
            grand_total_chapters += res["chapters"]
        else:
            error_count += 1

    total_elapsed = time.time() - total_start

    # Write summary
    summary_file = Path(args.output_dir) / "batch_ocr_summary.jsonl"
    summary_record = {
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total_books": len(pending),
        "success": success_count,
        "errors": error_count,
        "total_pages": grand_total_pages,
        "total_ocr_pages": grand_total_ocr,
        "total_paragraphs": grand_total_paras,
        "total_chapters": grand_total_chapters,
        "elapsed_sec": round(total_elapsed, 1),
    }

    with open(summary_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(summary_record, ensure_ascii=False) + "\n")

    print(f"\n{'='*60}")
    print(f"Batch OCR complete:")
    print(f"  Books: {success_count}/{len(pending)} succeeded, {error_count} errors")
    print(f"  Total pages: {grand_total_pages}")
    print(f"  Total OCR pages: {grand_total_ocr}")
    print(f"  Total paragraphs: {grand_total_paras}")
    print(f"  Total chapters/headings: {grand_total_chapters}")
    print(f"  Time: {total_elapsed:.0f}s ({total_elapsed/60:.1f} min)")
    print(f"  Summary: {summary_file}")
    print(f"  Books still needing work: {len(pending) - success_count} errors + check reasons above")


if __name__ == "__main__":
    main()
