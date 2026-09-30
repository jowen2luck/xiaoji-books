#!/usr/bin/env python3
"""
Merge OCR results from mobile_workshop/corpus into book-library-skill.

Source: D:\\Pcode\\play\\_apps\\mobile_workshop\\corpus\\
  book-xxxx.txt     — plain text with [Page N | Engine] headers
  book-xxxx.jsonl   — {page_num, char_count, text, engine, elapsed_s, status}

Target:
  data/corpus/books/book-xxxx.txt             — RAG-ready copy
  data/.ocr_reprocess/book-xxxx_pages.jsonl    — pipeline pages format
  data/.ocr_reprocess/book-xxxx_paragraphs.jsonl — chapter/section structure
  data/.ocr_reprocess/merge_mobile_summary.jsonl — merge report
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.pipeline.normalizer import normalize_text

SRC_DIR = Path(os.environ.get("MOBILE_CORPUS_DIR", r"D:\Pcode\play\_apps\mobile_workshop\corpus"))
LOG_FILE = Path(os.environ.get("MOBILE_LOG_FILE", r"D:\Pcode\play\_apps\mobile_workshop\evidence\stage2_completed_books.jsonl"))


def rebuild_paragraphs_for_pages(pages_file: Path, output_file: Path):
    """Run chapter/section detection on pages file, write paragraphs."""
    from scripts.verify.rebuild_paragraphs import rebuild_paragraphs_for_page

    paras = 0
    chapters = 0

    with open(pages_file, "r", encoding="utf-8") as fin, \
         open(output_file, "w", encoding="utf-8") as fout:

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


def main():
    parser = argparse.ArgumentParser(description="Merge mobile_workshop OCR corpus into book-library-skill")
    parser.add_argument("--output-pages", default="data/.ocr_reprocess")
    parser.add_argument("--output-corpus", default="data/corpus/books")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    output_pages = Path(args.output_pages)
    output_corpus = Path(args.output_corpus)
    if not args.dry_run:
        output_pages.mkdir(parents=True, exist_ok=True)
        output_corpus.mkdir(parents=True, exist_ok=True)

    # Load log entries
    log_entries = {}
    if LOG_FILE.exists():
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    bid = rec.get("book_id", "")
                    if bid:
                        log_entries[bid] = rec
                except json.JSONDecodeError:
                    continue

    # Discover .jsonl files in source
    jsonl_files = sorted(SRC_DIR.glob("*.jsonl"))
    if args.limit:
        jsonl_files = jsonl_files[: args.limit]

    print(f"Source .jsonl files: {len(jsonl_files)}")
    print(f"Log entries: {len(log_entries)}")

    results = []
    total_pages = 0
    total_paragraphs = 0
    total_chapters = 0
    success = 0
    errors = 0
    skipped = 0
    t0 = time.time()

    for jf in jsonl_files:
        book_id = jf.stem
        txt_file = SRC_DIR / f"{book_id}.txt"
        log = log_entries.get(book_id, {})
        out_pages_file = output_pages / f"{book_id}_pages.jsonl"

        rec = {"book_id": book_id, "status": "pending",
               "pages": 0, "paragraphs": 0, "chapters": 0,
               "error": None}

        # Skip if target already exists (local higher-DPI version)
        if out_pages_file.exists():
            rec["status"] = "skipped_exists"
            results.append(rec)
            skipped += 1
            print(f"  [SKIP] {book_id}: target exists (local version kept)")
            continue

        if not txt_file.exists():
            rec["status"] = "txt_missing"
            rec["error"] = f"{txt_file} not found"
            results.append(rec)
            errors += 1
            continue

        try:
            artifact_id = log.get("sha256", "")
            if artifact_id and not artifact_id.startswith("sha256:"):
                artifact_id = f"sha256:{artifact_id}"

            # Step 1: copy .txt to corpus/books
            if not args.dry_run:
                import shutil
                shutil.copy2(txt_file, output_corpus / f"{book_id}.txt")

            # Step 2: convert source.jsonl -> target _pages.jsonl
            pages_written = 0

            if not args.dry_run:
                fout = open(out_pages_file, "w", encoding="utf-8")
            else:
                fout = None

            with open(jf, "r", encoding="utf-8") as fin:
                for line in fin:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        sp = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    page_num = sp.get("page_num", 0)
                    page_index = page_num - 1  # target is 0-based
                    text_raw = sp.get("text", "")
                    extractor = sp.get("engine", "MobileOCR@unknown")

                    text_normalized, _, _ = normalize_text(text_raw)

                    tp = {
                        "id": f"{book_id}:p{page_index}",
                        "book_id": book_id,
                        "artifact_id": artifact_id,
                        "page_index": page_index,
                        "printed_page": str(page_num),
                        "text_raw": text_raw,
                        "text_normalized": text_normalized,
                        "normalization_version": "norm_v1",
                        "extractor": extractor,
                        "extractor_version": "mobile_v1",
                        "confidence": 0.9 if text_raw.strip() else 0.0,
                        "ocr_fallback_used": True,
                        "block_count": text_raw.count("\n") + 1 if text_raw else 0,
                        "evidence_set_id": f"es-mobile-{book_id}",
                    }

                    if fout:
                        fout.write(json.dumps(tp, ensure_ascii=False) + "\n")
                    pages_written += 1

            if fout:
                fout.close()

            rec["pages"] = pages_written
            total_pages += pages_written

            # Step 3: rebuild paragraphs (chapter/section structure)
            para_file = output_pages / f"{book_id}_paragraphs.jsonl"
            if not args.dry_run and pages_written > 0:
                paras, chapters = rebuild_paragraphs_for_pages(out_pages_file, para_file)
                rec["paragraphs"] = paras
                rec["chapters"] = chapters
                total_paragraphs += paras
                total_chapters += chapters
                print(f"  [OK] {book_id}: {pages_written} pages, {paras} paras, {chapters} chapters")
            elif args.dry_run:
                print(f"  [OK] {book_id}: {pages_written} pages (dry-run)")
            else:
                print(f"  [OK] {book_id}: {pages_written} pages")

            rec["status"] = "success"
            success += 1

        except Exception as e:
            rec["status"] = "error"
            rec["error"] = str(e)[:300]
            errors += 1
            print(f"  [FAIL] {book_id}: {str(e)[:200]}")

        results.append(rec)

    # Summary
    elapsed = time.time() - t0
    summary_file = Path(args.output_pages) / "merge_mobile_summary.jsonl"
    summary = {
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total": len(jsonl_files),
        "success": success,
        "skipped": skipped,
        "errors": errors,
        "total_pages": total_pages,
        "total_paragraphs": total_paragraphs,
        "total_chapters": total_chapters,
        "elapsed_sec": round(elapsed, 1),
        "dry_run": args.dry_run,
    }

    print(f"\n{'='*60}")
    print(f"Merge {'DRY-RUN ' if args.dry_run else ''}complete:")
    print(f"  Books: {success} merged / {skipped} skipped (exists) / {errors} errors")
    print(f"  Total pages: {total_pages}")
    print(f"  Total paragraphs: {total_paragraphs}")
    print(f"  Total chapters/headings: {total_chapters}")
    print(f"  Time: {elapsed:.0f}s ({elapsed/60:.1f} min)")

    if not args.dry_run:
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(summary, ensure_ascii=False) + "\n")
        print(f"  Summary: {summary_file}")

        checkpoint_file = Path(args.output_pages) / "merge_checkpoint.jsonl"
        with open(checkpoint_file, "w", encoding="utf-8") as f:
            for r in results:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"  Checkpoint: {checkpoint_file}")


if __name__ == "__main__":
    main()
