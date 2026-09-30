#!/usr/bin/env python3
"""
OCR Reprocessor — re-process PDFs that were misclassified as text_extractable.

Uses the fixed is_page_text_sufficient function to correctly identify
label-only pages and fall back to OCR.

Reads from diagnose_content_quality.jsonl to get the list of books needing OCR.
"""

import json
import os
import sys
import io
import time
from pathlib import Path

# Suppress noise
sys.stderr = io.StringIO()

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.pipeline.text_extract import extract_pdf_text, is_page_text_sufficient, compute_sha256
from scripts.pipeline.normalizer import normalize_text


def load_diagnose_results(path: str = "data/diagnose_content_quality.jsonl") -> list:
    """Load books needing OCR from diagnostic report."""
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if rec.get("overall", {}).get("recommendation") in (
                    "NEEDS_FULL_OCR",
                    "PARTIAL_TEXT_NEEDS_OCR",
                ):
                    records.append(rec)
            except json.JSONDecodeError:
                continue
    return records


def reprocess_book(
    book_id: str,
    pdf_path: str,
    output_dir: str = "data/.ocr_reprocess",
    dpi: int = 200,
) -> dict:
    """Re-process a single PDF with the improved pipeline (OCR fallback)."""
    start_time = time.time()

    result = {
        "book_id": book_id,
        "pdf_path": pdf_path,
        "status": "pending",
        "pages": 0,
        "paragraphs": 0,
        "text_pages": 0,
        "ocr_pages": 0,
        "elapsed_sec": 0,
        "error": None,
    }

    if not Path(pdf_path).exists():
        result["status"] = "file_not_found"
        return result

    try:
        # Run extraction — improved is_page_text_sufficient will trigger OCR for label-only pages
        extraction = extract_pdf_text(
            pdf_path=pdf_path,
            book_id=book_id,
            status="text_extractable",  # Keep original status; the improved check handles fallback
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
                "extractor_version": "improved_v2",
                "confidence": page.get("confidence", 0.0),
                "ocr_fallback_used": "ocr" in extractor,
                "block_count": page.get("block_count", 0),
                "evidence_set_id": f"es-reprocess-{book_id}",
            }
            output_pages.append(page_record)

        result["text_pages"] = text_pages
        result["ocr_pages"] = ocr_pages

        # Write output
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        out_file = out_path / f"{book_id}_pages.jsonl"

        with open(out_file, "w", encoding="utf-8") as f:
            for pr in output_pages:
                f.write(json.dumps(pr, ensure_ascii=False) + "\n")

        result["status"] = "success"
        result["output_file"] = str(out_file)

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    result["elapsed_sec"] = round(time.time() - start_time, 1)
    return result


def setup_signal_handler():
    """Enable graceful shutdown on SIGINT/SIGTERM."""
    import signal
    global _should_stop
    _should_stop = False

    def handler(signum, frame):
        global _should_stop
        _should_stop = True
        print("\n  (!) Received stop signal, finishing current page then exiting...")

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)


_should_stop = False


def main():
    setup_signal_handler()
    import argparse
    parser = argparse.ArgumentParser(description="Reprocess PDFs needing OCR")
    parser.add_argument("--diagnose", default="data/diagnose_content_quality.jsonl",
                       help="Path to diagnose results")
    parser.add_argument("--output-dir", default="data/.ocr_reprocess",
                       help="Output directory for reprocessed pages")
    parser.add_argument("--limit", type=int, default=None,
                       help="Limit number of books to process")
    parser.add_argument("--dpi", type=int, default=200,
                       help="OCR DPI")
    args = parser.parse_args()

    sys.stderr = sys.__stderr__

    # Ensure output dir exists upfront
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)

    books = load_diagnose_results(args.diagnose)
    print(f"Found {len(books)} books needing OCR reprocessing")

    # Resume: skip books that already have output files
    pending_books = []
    for book in books:
        book_id = book.get("book_id", "")
        out_file = Path(args.output_dir) / f"{book_id}_pages.jsonl"
        if out_file.exists() and out_file.stat().st_size > 100:
            print(f"  Skip (done): {book_id}")
            continue
        pending_books.append(book)

    if len(pending_books) < len(books):
        print(f"  Resuming: {len(pending_books)} pending / {len(books)} total")

    books = pending_books
    if not books:
        print("All books already processed. Nothing to do.")
        return

    # Sort by page count ascending (process smaller books first for quick wins)
    books.sort(key=lambda b: b.get("page_count", 0))

    if args.limit:
        books = books[:args.limit]
        print(f"  (limited to first {args.limit})")

    results = []
    for i, book in enumerate(books):
        book_id = book.get("book_id", "unknown")
        pdf_path = book.get("pdf_path", "")
        pages = book.get("page_count", 0)

        print(f"[{i+1}/{len(books)}] {book_id} ({pages} pages)...")

        res = reprocess_book(book_id, pdf_path, args.output_dir, args.dpi)
        results.append(res)

        status_icon = "PASS" if res["status"] == "success" else "FAIL"
        err_msg = res.get("error", "")
        extra_msg = f" | ERROR: {err_msg[:120]}" if err_msg else ""
        print(f"  {status_icon}: {res['status']} | text={res['text_pages']} ocr={res['ocr_pages']} "
              f"| {res['elapsed_sec']}s{extra_msg}")

    # Summary
    ok_count = sum(1 for r in results if r["status"] == "success")
    total_ocr_pages = sum(r.get("ocr_pages", 0) for r in results)
    total_text_pages = sum(r.get("text_pages", 0) for r in results)
    total_time = sum(r.get("elapsed_sec", 0) for r in results)

    print(f"\n{'='*60}")
    print(f"Reprocessing complete:")
    print(f"  Books: {ok_count}/{len(results)} succeeded")
    print(f"  Total OCR pages: {total_ocr_pages}")
    print(f"  Total text pages: {total_text_pages}")
    print(f"  Total time: {total_time:.0f}s ({total_time/60:.1f} min)")

    # Write summary
    summary_path = Path(args.output_dir) / "reprocess_summary.jsonl"
    with open(summary_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"  Summary: {summary_path}")


if __name__ == "__main__":
    main()
