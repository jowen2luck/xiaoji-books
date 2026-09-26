#!/usr/bin/env python3
"""
Content Quality Diagnoser for book-library-scanner.

Scans all PDFs classified as "text_extractable" and determines
whether they actually contain meaningful text content or just
labels/metadata/tags that should have been OCR'd instead.

Outputs a JSONL report with recommendations for each PDF.
"""

import json
import re
import os
import sys
import io
from pathlib import Path
from typing import Optional, Tuple

# Suppress pdfplumber noise
sys.stderr = io.StringIO()

import fitz  # PyMuPDF

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

# ─── Thresholds ──────────────────────────────────────────────
MIN_CJK_CHARS = 30        # minimum CJK characters per page
MIN_TOTAL_CHARS = 80      # minimum total chars per page
MIN_LINES = 3             # minimum lines of actual text
MIN_AVG_LINE_LEN = 15     # minimum average line length

# Patterns that indicate "label-only" content
LABEL_PATTERNS = [
    r'^\s*[\w\-]+\s*$',                    # single word/identifier
    r'^\s*\d+\s*$',                        # just a page number
    r'^\s*第\s*\d+\s*页\s*$',              # "第X页"
    r'^\s*Page\s+\d+\s*$',                 # "Page X"
    r'^\s*www\.\S+\s*$',                   # URL only
    r'^\s*https?://\S+\s*$',               # URL only
]


def count_cjk(text: str) -> int:
    """Count CJK characters in text."""
    return len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf]', text))


def count_meaningful_lines(text: str) -> int:
    """Count lines that have actual content (not just labels)."""
    lines = text.split('\n')
    meaningful = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Skip lines that are just labels/numbers
        is_label = False
        for pattern in LABEL_PATTERNS:
            if re.match(pattern, stripped, re.IGNORECASE):
                is_label = True
                break
        if not is_label and len(stripped) >= 5:
            meaningful += 1
    return meaningful


def compute_content_score(text: str) -> dict:
    """
    Score the content quality of extracted text.
    Returns a dict with various metrics.
    """
    if not text or not text.strip():
        return {
            "total_chars": 0,
            "cjk_chars": 0,
            "line_count": 0,
            "meaningful_lines": 0,
            "avg_line_length": 0.0,
            "weighted_score": 0.0,
            "is_meaningful": False,
        }

    lines = [l for l in text.split('\n') if l.strip()]
    total_chars = len(text.strip())
    cjk_chars = count_cjk(text)
    line_count = len(lines)
    meaningful_lines = count_meaningful_lines(text)
    avg_line_len = total_chars / max(line_count, 1)

    # Weighted score
    score = 0.0
    score += min(cjk_chars / MIN_CJK_CHARS, 3.0) * 2.0   # CJK chars weighted heavily
    score += min(total_chars / MIN_TOTAL_CHARS, 3.0) * 1.0
    score += min(meaningful_lines / MIN_LINES, 3.0) * 1.5
    score += min(avg_line_len / MIN_AVG_LINE_LEN, 2.0) * 0.5

    is_meaningful = (
        cjk_chars >= MIN_CJK_CHARS
        and total_chars >= MIN_TOTAL_CHARS
        and meaningful_lines >= MIN_LINES
        and score >= 3.0
    )

    return {
        "total_chars": total_chars,
        "cjk_chars": cjk_chars,
        "line_count": line_count,
        "meaningful_lines": meaningful_lines,
        "avg_line_length": round(avg_line_len, 1),
        "weighted_score": round(score, 2),
        "is_meaningful": is_meaningful,
    }


def sample_pdf_pages(pdf_path: str, sample_ratio: float = 0.1) -> list:
    """
    Sample pages from a PDF and return (page_index, text) tuples.
    Samples first 10%, middle 10%, and last 10% by default.
    """
    doc = fitz.open(pdf_path)
    total = doc.page_count
    if total == 0:
        doc.close()
        return []

    # Determine sample indices
    n_samples = max(3, int(total * sample_ratio))
    indices = set()

    # First pages
    for i in range(min(3, total)):
        indices.add(i)

    # Middle pages
    mid_start = total // 2 - n_samples // 2
    for i in range(max(0, mid_start), min(mid_start + n_samples, total)):
        indices.add(i)

    # Last pages
    for i in range(max(0, total - 3), total):
        indices.add(i)

    results = []
    for idx in sorted(indices):
        try:
            page = doc.load_page(idx)
            text = page.get_text("text").strip()
            results.append((idx, text))
        except Exception:
            results.append((idx, ""))

    doc.close()
    return results


def diagnose_pdf(pdf_path: str, book_id: str = "") -> dict:
    """
    Run full content quality diagnosis on a PDF.
    Uses PyMuPDF (fast) + optional pdfplumber verification.
    """
    result = {
        "book_id": book_id,
        "pdf_path": pdf_path,
        "page_count": 0,
        "sampled_pages": [],
        "overall": {
            "pages_meaningful": 0,
            "pages_empty": 0,
            "pages_label_only": 0,
            "avg_cjk_chars": 0.0,
            "avg_total_chars": 0.0,
            "needs_ocr": False,
            "recommendation": "",
        },
    }

    if not Path(pdf_path).exists():
        result["overall"]["recommendation"] = "FILE_NOT_FOUND"
        return result

    # Get page count
    try:
        doc = fitz.open(pdf_path)
        result["page_count"] = doc.page_count
        doc.close()
    except Exception as e:
        result["overall"]["recommendation"] = f"CANNOT_OPEN: {e}"
        return result

    if result["page_count"] == 0:
        result["overall"]["recommendation"] = "EMPTY_PDF"
        return result

    # Sample pages
    samples = sample_pdf_pages(pdf_path)
    if not samples:
        result["overall"]["recommendation"] = "SAMPLING_FAILED"
        return result

    total_cjk = 0
    total_chars_count = 0
    meaningful_pages = 0
    empty_pages = 0
    label_only_pages = 0

    for page_idx, pymupdf_text in samples:
        score = compute_content_score(pymupdf_text)

        page_result = {
            "page_index": page_idx,
            **score,
        }

        # If PyMuPDF finds nothing, try pdfplumber for verification
        if not score["is_meaningful"] and pdfplumber is not None:
            try:
                with pdfplumber.open(pdf_path) as pdf:
                    if page_idx < len(pdf.pages):
                        page = pdf.pages[page_idx]
                        pb_text = (page.extract_text() or "").strip()
                        pb_score = compute_content_score(pb_text)
                        if pb_score["is_meaningful"]:
                            page_result["pdfplumber_text"] = pb_text[:200]
                            page_result["pdfplumber_score"] = pb_score["weighted_score"]
                            # Override with pdfplumber result
                            score = pb_score
                            page_result.update({
                                "cjk_chars": score["cjk_chars"],
                                "total_chars": score["total_chars"],
                                "meaningful_lines": score["meaningful_lines"],
                                "weighted_score": score["weighted_score"],
                                "is_meaningful": score["is_meaningful"],
                            })
            except Exception:
                pass

        if score["is_meaningful"]:
            meaningful_pages += 1
        elif score["total_chars"] == 0:
            empty_pages += 1
        else:
            label_only_pages += 1

        total_cjk += score["cjk_chars"]
        total_chars_count += score["total_chars"]
        result["sampled_pages"].append(page_result)

    n = len(samples)
    result["overall"]["avg_cjk_chars"] = round(total_cjk / n, 1)
    result["overall"]["avg_total_chars"] = round(total_chars_count / n, 1)
    result["overall"]["pages_meaningful"] = meaningful_pages
    result["overall"]["pages_empty"] = empty_pages
    result["overall"]["pages_label_only"] = label_only_pages

    # Determine recommendation
    meaningful_ratio = meaningful_pages / n if n > 0 else 0

    if meaningful_ratio >= 0.7:
        result["overall"]["needs_ocr"] = False
        result["overall"]["recommendation"] = "TEXT_OK"
    elif meaningful_ratio >= 0.3 and (total_cjk / n) >= MIN_CJK_CHARS:
        result["overall"]["needs_ocr"] = True
        result["overall"]["recommendation"] = "PARTIAL_TEXT_NEEDS_OCR"
    else:
        result["overall"]["needs_ocr"] = True
        result["overall"]["recommendation"] = "NEEDS_FULL_OCR"

    return result


def load_manifest(manifest_path: str = "data/manifest.jsonl") -> list:
    """Load manifest records from JSONL file."""
    records = []
    path = Path(manifest_path)
    if not path.exists():
        print(f"Manifest not found: {manifest_path}", file=sys.stderr)
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


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Diagnose PDF content quality")
    parser.add_argument("--manifest", default="data/manifest.jsonl",
                       help="Path to manifest.jsonl")
    parser.add_argument("--output", default="data/diagnose_content_quality.jsonl",
                       help="Output path for diagnosis report")
    parser.add_argument("--filter-status", default="text_extractable",
                       help="Only check PDFs with this manifest status")
    parser.add_argument("--sample-ratio", type=float, default=0.1,
                       help="Ratio of pages to sample (0.0-1.0)")
    parser.add_argument("--limit", type=int, default=None,
                       help="Limit number of PDFs to diagnose")
    args = parser.parse_args()

    # Redirect stderr for pdfplumber noise
    old_stderr = sys.stderr
    sys.stderr = io.StringIO()

    manifest_records = load_manifest(args.manifest)
    sys.stderr = old_stderr

    if not manifest_records:
        print("No manifest records found.", file=sys.stderr)
        sys.exit(1)

    # Filter by status
    if args.filter_status:
        manifest_records = [r for r in manifest_records
                           if r.get("status") == args.filter_status]

    if args.limit:
        manifest_records = manifest_records[:args.limit]

    print(f"Loaded {len(manifest_records)} records with status={args.filter_status}",
          file=sys.stderr)

    # Diagnose each PDF
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    results = []
    needs_ocr_count = 0

    for i, rec in enumerate(manifest_records):
        pdf_path = rec.get("source_full_path", "")
        book_id = rec.get("book_id", "")

        if i % 10 == 0:
            print(f"  [{i+1}/{len(manifest_records)}] {book_id}...", file=sys.stderr)

        diag = diagnose_pdf(pdf_path, book_id)
        results.append(diag)

        if diag["overall"]["needs_ocr"]:
            needs_ocr_count += 1

        # Write incrementally
        with open(output_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(diag, ensure_ascii=False) + "\n")

    print(f"\nDone. Diagnosed {len(manifest_records)} PDFs.", file=sys.stderr)
    print(f"  Needs OCR: {needs_ocr_count}", file=sys.stderr)
    print(f"  OK: {len(manifest_records) - needs_ocr_count}", file=sys.stderr)
    print(f"Output: {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
