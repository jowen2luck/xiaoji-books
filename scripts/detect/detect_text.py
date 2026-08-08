#!/usr/bin/env python3
"""
PDF Text Extractability Detector

Classifies PDFs into four categories:
  - text_extractable: Has extractable text (no OCR needed)
  - ocr_required: No extractable text (OCR needed)
  - partial_text: Some pages have text, others need OCR
  - parser_error: Cannot parse the PDF

Uses pdfplumber (primary) and pypdf (fallback) to sample pages.
"""

import json
import sys
import os
import argparse
import warnings
from pathlib import Path
from typing import Optional

# Suppress pdfplumber's verbose warnings about malformed PDFs
# pdfplumber writes directly to stderr (not via warnings module)
import io
sys.stderr = io.StringIO()

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

try:
    import pypdf
except ImportError:
    pypdf = None


# Minimum character count to consider a page as "has meaningful text"
MIN_CHARS_PER_PAGE = 50

# Pages to sample: first 3, middle 3, last 3 (auto-adjusted for small PDFs)
SAMPLE_PAGES_START = 3
SAMPLE_PAGES_MID = 3
SAMPLE_PAGES_END = 3


def get_sample_page_indices(total_pages: int) -> list[int]:
    """Get 0-based page indices to sample from first, middle, end."""
    if total_pages <= 0:
        return []
    
    indices = set()
    # First N pages
    for i in range(min(SAMPLE_PAGES_START, total_pages)):
        indices.add(i)
    
    # Middle N pages
    mid_start = max(0, total_pages // 2 - SAMPLE_PAGES_MID // 2)
    for i in range(mid_start, min(mid_start + SAMPLE_PAGES_MID, total_pages)):
        indices.add(i)
    
    # Last N pages
    for i in range(max(0, total_pages - SAMPLE_PAGES_END), total_pages):
        indices.add(i)
    
    return sorted(indices)


def extract_text_from_page_plumber(pdf_path: str, page_num: int) -> Optional[str]:
    """Extract text from a single page using pdfplumber."""
    if pdfplumber is None:
        return None
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if page_num >= len(pdf.pages):
                return None
            page = pdf.pages[page_num]
            text = page.extract_text() or ""
            return text.strip()
    except Exception:
        return None


def extract_text_from_page_pypdf(pdf_path: str, page_num: int) -> Optional[str]:
    """Extract text from a single page using pypdf (fallback)."""
    if pypdf is None:
        return None
    try:
        reader = pypdf.PdfReader(pdf_path)
        if page_num >= len(reader.pages):
            return None
        page = reader.pages[page_num]
        text = page.extract_text() or ""
        return text.strip()
    except Exception:
        return None


def extract_text_from_page(pdf_path: str, page_num: int) -> Optional[str]:
    """Try pdfplumber first, then pypdf as fallback."""
    text = extract_text_from_page_plumber(pdf_path, page_num)
    if text is not None and len(text) >= MIN_CHARS_PER_PAGE:
        return text
    # Fallback to pypdf
    text = extract_text_from_page_pypdf(pdf_path, page_num)
    return text


def get_total_pages(pdf_path: str) -> Optional[int]:
    """Get total page count. Returns None on error."""
    # Try pypdf first (fast)
    if pypdf is not None:
        try:
            reader = pypdf.PdfReader(pdf_path)
            return len(reader.pages)
        except Exception:
            pass
    # Fallback to pdfplumber
    if pdfplumber is not None:
        try:
            with pdfplumber.open(pdf_path) as pdf:
                return len(pdf.pages)
        except Exception:
            pass
    return None


def classify_pdf(pdf_path: str) -> dict:
    """Classify a single PDF file. Returns a dict with classification result."""
    result = {
        "file_path": str(pdf_path),
        "status": "parser_error",
        "total_pages": 0,
        "sampled_pages": 0,
        "pages_with_text": 0,
        "pages_without_text": 0,
        "sample_details": [],
        "error": None,
    }
    
    total_pages = get_total_pages(pdf_path)
    if total_pages is None:
        result["error"] = "Cannot determine page count"
        return result
    
    result["total_pages"] = total_pages
    
    sample_indices = get_sample_page_indices(total_pages)
    if not sample_indices:
        result["error"] = "No sample pages available"
        return result
    
    result["sampled_pages"] = len(sample_indices)
    
    for page_idx in sample_indices:
        page_result = {
            "page_index": page_idx,
            "has_text": False,
            "char_count": 0,
        }
        text = extract_text_from_page(pdf_path, page_idx)
        if text is not None and len(text) >= MIN_CHARS_PER_PAGE:
            page_result["has_text"] = True
            page_result["char_count"] = len(text)
            result["pages_with_text"] += 1
        else:
            result["pages_without_text"] += 1
        result["sample_details"].append(page_result)
    
    # Classify based on sample
    if result["pages_with_text"] == result["sampled_pages"]:
        result["status"] = "text_extractable"
    elif result["pages_with_text"] == 0:
        result["status"] = "ocr_required"
    elif result["pages_with_text"] > 0:
        result["status"] = "partial_text"
    
    return result


def read_archive_index(index_path: str) -> list[dict]:
    """Read archive-index.json and return list of PDF file entries."""
    with open(index_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    files = data.get("files", [])
    # Filter to PDF files only
    pdf_files = [f for f in files if f.get("type") == "pdf"]
    return pdf_files


def resolve_pdf_path(entry: dict, source_dir: str) -> Path:
    """Resolve the absolute path of a PDF from an archive-index entry."""
    rel_path = entry.get("path", "").replace("\\", os.sep).replace("/", os.sep)
    return Path(source_dir) / rel_path


def main():
    parser = argparse.ArgumentParser(description="Detect PDF text extractability")
    parser.add_argument("--index", default="data/archive-index.json",
                        help="Path to archive-index.json")
    parser.add_argument("--source-dir", default="data/_kage/www.marxists.org",
                        help="Base directory where PDFs are stored")
    parser.add_argument("--output", default="data/manifest-detection.jsonl",
                        help="Output JSONL file with detection results")
    parser.add_argument("--single", type=str, default=None,
                        help="Path to a single PDF to classify")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print verbose output")
    
    args = parser.parse_args()
    
    if args.single:
        # Single file mode
        result = classify_pdf(args.single)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    
    # Batch mode using archive-index
    entries = read_archive_index(args.index)
    if not entries:
        print("ERROR: No PDF entries found in archive-index.json", file=sys.stderr)
        sys.exit(1)
    
    print(f"Processing {len(entries)} PDF entries...")
    
    results = []
    counts = {"text_extractable": 0, "ocr_required": 0, "partial_text": 0, "parser_error": 0}
    
    for i, entry in enumerate(entries):
        pdf_path = resolve_pdf_path(entry, args.source_dir)
        
        if not pdf_path.exists():
            result = {
                "file_path": str(pdf_path),
                "status": "parser_error",
                "error": "File not found",
            }
        else:
            result = classify_pdf(str(pdf_path))
        
        # Add metadata from archive-index
        result["archive_id"] = entry.get("id", "")
        result["subcategory"] = entry.get("subcategory", "")
        result["stem"] = entry.get("stem", "")
        result["size_bytes"] = entry.get("size_bytes", 0)
        
        results.append(result)
        counts[result["status"]] += 1
        
        if args.verbose:
            status_mark = {"text_extractable": "T", "ocr_required": "O",
                          "partial_text": "P", "parser_error": "E"}.get(result["status"], "?")
            print(f"  [{status_mark}] {entry.get('stem', pdf_path.name):20s} -> {result['status']}")
        
        # Progress indicator
        if (i + 1) % 100 == 0:
            print(f"  Progress: {i+1}/{len(entries)}")
    
    # Write output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    
    # Summary
    print(f"\nDetection complete: {len(entries)} PDFs processed")
    print(f"  text_extractable: {counts['text_extractable']}  ({counts['text_extractable']*100//len(entries)}%)")
    print(f"  ocr_required:     {counts['ocr_required']}  ({counts['ocr_required']*100//len(entries)}%)")
    print(f"  partial_text:     {counts['partial_text']}  ({counts['partial_text']*100//len(entries)}%)")
    print(f"  parser_error:     {counts['parser_error']}  ({counts['parser_error']*100//len(entries)}%)")
    print(f"\nResults written to: {output_path}")


if __name__ == "__main__":
    main()
