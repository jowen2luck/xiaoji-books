#!/usr/bin/env python3
"""
PDF Ingestion Pipeline (M1+: manifest-driven book_id)

Reads book_id from data/manifest.jsonl (NEVER derives from filename).
Two parallel paths remain:
  1. Text extraction (text_extractable / partial_text)
  2. OCR (ocr_required) - calls scripts/pipeline/ocr_extract.py

Outputs unified Evidence records to data/evidence/
"""

import json
import os
import sys
import hashlib
import argparse
import warnings
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

# Suppress pdfplumber malformed PDF warnings
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


# Version identifiers
EXTRACTOR_PDFPLUMBER = "pdfplumber@0.11.10"
EXTRACTOR_PYPDF = "pypdf@6.14.2"
NORMALIZATION_VERSION = "norm_v1"


def load_manifest(manifest_path: str) -> dict:
    """
    Load manifest.jsonl into {path: record} mapping.
    """
    manifest = {}
    with open(manifest_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("source_full_path"):
                manifest[record["source_full_path"]] = record
            if record.get("source_path"):
                manifest[record["source_path"]] = record
                manifest[record["source_path"].replace("/", "\\")] = record
    return manifest


def lookup_book_id(manifest: dict, file_path: str) -> Optional[str]:
    """Look up book_id from manifest by file path."""
    if file_path in manifest:
        return manifest[file_path]["book_id"]
    abs_path = str(Path(file_path).resolve())
    if abs_path in manifest:
        return manifest[abs_path]["book_id"]
    forward = file_path.replace("\\", "/")
    if forward in manifest:
        return manifest[forward]["book_id"]
    backward = file_path.replace("/", "\\")
    if backward in manifest:
        return manifest[backward]["book_id"]
    return None


def compute_sha256(file_path: str) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_text(text: str) -> str:
    """
    Apply mechanical normalization rules.
    
    Allowed (norm_v1):
    - Fullwidth to halfwidth for ASCII
    - CJK spacing fix
    - Strip head/tail whitespace
    - Unify newlines
    """
    if not text:
        return ""
    
    # Unify newlines first
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    
    # Fullwidth to halfwidth for ASCII range
    result = []
    for ch in text:
        code = ord(ch)
        # Fullwidth ASCII variants: U+FF01 to U+FF5E
        if 0xFF01 <= code <= 0xFF5E:
            result.append(chr(code - 0xFEE0))
        # Fullwidth space: U+3000 -> U+0020
        elif code == 0x3000:
            result.append(" ")
        else:
            result.append(ch)
    text = "".join(result)
    
    # CJK spacing: remove spaces between CJK characters
    import re
    # CJK ranges: U+4E00-U+9FFF (common), U+3400-U+4DBF (ext A)
    cjk_char = r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]"
    text = re.sub(f"({cjk_char})\\s+({cjk_char})", r"\1\2", text)
    # Run multiple times to catch overlapping matches
    for _ in range(3):
        text = re.sub(f"({cjk_char})\\s+({cjk_char})", r"\1\2", text)
    
    # Strip each line's trailing whitespace, remove excessive blank lines
    lines = text.split("\n")
    lines = [l.rstrip() for l in lines]
    text = "\n".join(lines)
    
    # Remove more than 2 consecutive blank lines
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    
    return text.strip()


def split_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs by blank lines."""
    if not text:
        return []
    paragraphs = []
    current = []
    for line in text.split("\n"):
        if line.strip() == "":
            if current:
                paragraphs.append("\n".join(current))
                current = []
        else:
            current.append(line)
    if current:
        paragraphs.append("\n".join(current))
    return [p.strip() for p in paragraphs if p.strip()]


def extract_pages_plumber(pdf_path: str) -> list[dict]:
    """Extract text from each page using pdfplumber."""
    if pdfplumber is None:
        return []
    pages = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                text = ""
                try:
                    text = page.extract_text() or ""
                except Exception as e:
                    text = ""
                pages.append({
                    "page_index": i,
                    "text_raw": text,
                    "char_count": len(text),
                })
    except Exception as e:
        return []
    return pages


def extract_pages_pypdf(pdf_path: str) -> list[dict]:
    """Extract text from each page using pypdf (fallback)."""
    if pypdf is None:
        return []
    pages = []
    try:
        reader = pypdf.PdfReader(pdf_path)
        for i, page in enumerate(reader.pages):
            text = ""
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            pages.append({
                "page_index": i,
                "text_raw": text,
                "char_count": len(text),
            })
    except Exception:
        return []
    return pages


def extract_pages(pdf_path: str) -> tuple[list[dict], str]:
    """
    Extract pages with best available method.
    Returns (pages_data, extractor_name).
    """
    # Try pdfplumber first (usually better for complex layouts)
    if pdfplumber is not None:
        pages = extract_pages_plumber(pdf_path)
        if pages and any(p["char_count"] >= 20 for p in pages):
            return pages, EXTRACTOR_PDFPLUMBER
    
    # Fallback to pypdf
    if pypdf is not None:
        pages = extract_pages_pypdf(pdf_path)
        if pages:
            return pages, EXTRACTOR_PYPDF
    
    return [], "none"


def process_text_pdf(pdf_path: str, book_id: str) -> dict:
    """
    Process a text-extractable PDF.
    Returns a dict with metadata and evidence records.
    """
    source_hash = compute_sha256(pdf_path)
    artifact_id = f"sha256:{source_hash}"
    
    # Extract pages
    pages_data, extractor_used = extract_pages(pdf_path)
    
    if not pages_data:
        return {
            "book_id": book_id,
            "status": "parser_error",
            "error": "No pages could be extracted",
        }
    
    # Build evidence records
    books_record = {
        "type": "book_metadata",
        "book_id": book_id,
        "artifact_id": artifact_id,
        "source_path": str(pdf_path),
        "extractor": extractor_used,
        "extractor_version": extractor_used.split("@")[-1] if "@" in extractor_used else "unknown",
        "normalization_version": NORMALIZATION_VERSION,
        "total_pages": len(pages_data),
        "source_hash": source_hash,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "evidence_set_id": f"es-{source_hash[:12]}",
    }
    
    page_records = []
    paragraph_records = []
    
    for page_data in pages_data:
        page_idx = page_data["page_index"]
        text_raw = page_data["text_raw"]
        text_normalized = normalize_text(text_raw)
        
        page_id = f"{book_id}:p{page_idx}"
        
        # Page-level evidence
        page_records.append({
            "id": page_id,
            "type": "raw_page",
            "book_id": book_id,
            "artifact_id": artifact_id,
            "source_hash": source_hash,
            "page_index": page_idx,
            "text_raw": text_raw,
            "text_normalized": text_normalized,
            "normalization_version": NORMALIZATION_VERSION,
            "extractor": extractor_used,
            "extractor_version": extractor_used.split("@")[-1] if "@" in extractor_used else "unknown",
            "char_count": len(text_normalized),
            "ingested_at": books_record["ingested_at"],
            "evidence_set_id": books_record["evidence_set_id"],
        })
        
        # Paragraph-level evidence
        paragraphs = split_paragraphs(text_normalized)
        for para_idx, para_text in enumerate(paragraphs):
            if len(para_text.strip()) < 10:
                continue
            para_id = f":p{page_idx}:para{para_idx}"
            paragraph_records.append({
                "id": f"{book_id}{para_id}",
                "type": "raw_paragraph",
                "book_id": book_id,
                "artifact_id": artifact_id,
                "source_hash": source_hash,
                "page_id": page_id,
                "page_index": page_idx,
                "para_index": para_idx,
                "text_raw": text_raw,  # Raw page text as source
                "text_normalized": para_text,
                "normalization_version": NORMALIZATION_VERSION,
                "extractor": extractor_used,
                "extractor_version": extractor_used.split("@")[-1] if "@" in extractor_used else "unknown",
                "char_count": len(para_text),
                "ingested_at": books_record["ingested_at"],
                "evidence_set_id": books_record["evidence_set_id"],
            })
    
    return {
        "book_id": book_id,
        "status": "success",
        "metadata": books_record,
        "pages": page_records,
        "paragraphs": paragraph_records,
    }


def write_evidence(result: dict, output_dir: str):
    """Write evidence records to JSONL files."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    book_id = result["book_id"]
    
    # Write metadata
    meta_path = output_path / "books.jsonl"
    with open(meta_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(result["metadata"], ensure_ascii=False) + "\n")
    
    # Write pages
    if result.get("pages"):
        pages_path = output_path / "pages.jsonl"
        with open(pages_path, "a", encoding="utf-8") as f:
            for page in result["pages"]:
                f.write(json.dumps(page, ensure_ascii=False) + "\n")
    
    # Write paragraphs
    if result.get("paragraphs"):
        paras_path = output_path / "paragraphs.jsonl"
        with open(paras_path, "a", encoding="utf-8") as f:
            for para in result["paragraphs"]:
                f.write(json.dumps(para, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Ingest PDFs into Evidence")
    parser.add_argument("--input", default="data/manifest-detection.jsonl",
                        help="Detection results JSONL")
    parser.add_argument("--output", default="data/evidence/",
                        help="Output directory for evidence files")
    parser.add_argument("--single", type=str, default=None,
                        help="Single PDF path to ingest (book_id from manifest)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Only show what would be done")
    parser.add_argument("--status-filter", type=str, default="text_extractable",
                        help="Only ingest PDFs with this status (comma-separated)")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--manifest", default="data/manifest.jsonl",
                        help="Path to manifest.jsonl (stable book_id source)")
    
    args = parser.parse_args()
    
    # Load manifest — book_id must come from manifest, never derived from filename
    manifest = load_manifest(args.manifest) if Path(args.manifest).exists() else {}
    
    if args.single:
        # Single file mode — book_id from manifest only (no filename derivation)
        book_id = lookup_book_id(manifest, args.single)
        if not book_id:
            print(f"ERROR: {args.single} not found in manifest ({args.manifest})")
            print("Run scripts/detect/generate_manifest.py first to register this file.")
            return
        if args.dry_run:
            print(f"[DRY-RUN] Would ingest: {args.single} -> book_id={book_id}")
            return
        result = process_text_pdf(args.single, book_id)
        print(json.dumps({
            "book_id": result["book_id"],
            "status": result["status"],
            "total_pages": len(result.get("pages", [])),
            "total_paragraphs": len(result.get("paragraphs", [])),
            "evidence_set_id": result.get("metadata", {}).get("evidence_set_id", ""),
        }, ensure_ascii=False, indent=2))
        if result["status"] == "success":
            write_evidence(result, args.output)
            print(f"Evidence written to {args.output}")
        return
    
    # Batch mode
    results = []
    with open(args.input, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                results.append(json.loads(line))
    
    status_filter = set(args.status_filter.split(","))
    to_ingest = [r for r in results if r["status"] in status_filter]
    
    print(f"Total in manifest: {len(results)}")
    print(f"Filtering by status: {status_filter}")
    print(f"To ingest: {len(to_ingest)}")
    
    if args.dry_run:
        print("[DRY-RUN] No files will be written")
        for r in to_ingest[:5]:
            print(f"  - {r.get('stem', '')} ({r['status']})")
        if len(to_ingest) > 5:
            print(f"  ... and {len(to_ingest) - 5} more")
        return
    
    # Ingest each PDF
    success_count = 0
    error_count = 0
    
    for i, entry in enumerate(to_ingest):
        pdf_path = entry.get("file_path", "")
        stem = entry.get("stem", "")
        # book_id from manifest — filename is NEVER the source of book_id
        book_id = lookup_book_id(manifest, pdf_path)
        if not book_id:
            print(f"  [{i+1}/{len(to_ingest)}] SKIP (no manifest entry): {stem}")
            error_count += 1
            continue
        
        if not Path(pdf_path).exists():
            print(f"  [{i+1}/{len(to_ingest)}] SKIP (not found): {stem}")
            error_count += 1
            continue
        
        try:
            result = process_text_pdf(pdf_path, book_id)
            if result["status"] == "success":
                write_evidence(result, args.output)
                success_count += 1
                if args.verbose:
                    print(f"  [{i+1}/{len(to_ingest)}] OK: {stem} "
                          f"({len(result['pages'])} pages, {len(result['paragraphs'])} paras)")
            else:
                error_count += 1
                print(f"  [{i+1}/{len(to_ingest)}] FAIL: {stem} - {result.get('error', 'unknown')}")
        except Exception as e:
            error_count += 1
            print(f"  [{i+1}/{len(to_ingest)}] ERROR: {stem} - {e}")
    
    print(f"\nIngest complete: {success_count} success, {error_count} errors")
    print(f"Evidence written to: {args.output}")


if __name__ == "__main__":
    main()
