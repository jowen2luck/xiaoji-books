"""Batch Ingest — process all PDFs in manifest with checkpoint/resume.

Orchestrates text_extract + ocr_extract pipelines against manifest entries
and writes Evidence JSONL files (books, pages, paragraphs).

Features:
- Checkpoint/resume via JSONL log: each book's completion is logged
- Per-status dispatch: text_extractable → text_extract, ocr_required → ocr
- partial_text → text_extract with per-page OCR fallback
- Error isolation: one book's failure doesn't block others
- Progress reporting + ETA

Usage:
    python scripts/pipeline/batch_ingest.py --status-filter text_extractable --limit 10
    python scripts/pipeline/batch_ingest.py --status-filter ocr_required --limit 5
    python scripts/pipeline/batch_ingest.py  # process all, resume from checkpoint
"""
import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(manifest_path):
    """Load manifest — return list of records with source_full_path resolved."""
    records = []
    with open(manifest_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def resolve_pdf_path(record, base_dir):
    """Resolve the full filesystem path for a manifest record."""
    for key in ("source_full_path", "source_path"):
        rel = record.get(key)
        if rel:
            # Try direct
            direct = Path(rel)
            if direct.is_absolute() and direct.exists():
                return str(direct)
            # Try relative to base
            based = Path(base_dir) / rel
            if based.exists():
                return str(based)
            # Try with forward/backward slash normalization
            rel_norm = rel.replace("\\", "/")
            based_norm = Path(base_dir) / rel_norm
            if based_norm.exists():
                return str(based_norm)
    return None


def resolve_from_checkpoint(checkpoint_path, book_id, evidence_set_id=""):
    """Check if a (book_id, evidence_set_id) was already processed successfully.
    
    If evidence_set_id is given, only skip when BOTH match (version-aware).
    If missing, fall back to book_id-only for backward compat.
    """
    if not os.path.exists(checkpoint_path):
        return False
    with open(checkpoint_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if rec.get("status") != "success":
                    continue
                if rec.get("book_id") != book_id:
                    continue
                if evidence_set_id:
                    if rec.get("evidence_set_id") == evidence_set_id:
                        return True
                else:
                    return True
            except Exception:
                pass
    return False


def append_checkpoint(checkpoint_path, entry):
    """Append a checkpoint entry."""
    with open(checkpoint_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def append_jsonl(filepath, record):
    """Append a record to a JSONL file (creates if doesn't exist)."""
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def make_parser():
    parser = argparse.ArgumentParser(description="Batch PDF ingest with checkpoint/resume")
    parser.add_argument("--manifest", default="data/manifest.jsonl")
    parser.add_argument("--base-dir", default="data/_kage/www.marxists.org",
                       help="Base directory for resolving relative PDF paths")
    parser.add_argument("--status-filter", default="all",
                       help="Comma-separated: text_extractable,ocr_required,partial_text,parser_error,or 'all'")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--poppler-path", default=None)
    parser.add_argument("--output-dir", default="data/evidence")
    parser.add_argument("--checkpoint", default="data/batch_checkpoint.jsonl")
    parser.add_argument("--max-pages-per-book", type=int, default=None,
                       help="Cap pages processed per book (for testing)")
    parser.add_argument("--onnx-threads", type=int, default=2,
                       help="ONNX intra-op threads per sub-engine (default 2, safe for 4 parallel workers)")
    parser.add_argument("--no-resume", action="store_true",
                       help="Ignore checkpoint, reprocess everything")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main():
    parser = make_parser()
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parent))

    # Load manifest
    manifest = load_manifest(args.manifest)
    print(f"Loaded manifest: {len(manifest)} entries", file=sys.stderr)

    # Filter by status
    if args.status_filter == "all":
        target_statuses = {"text_extractable", "ocr_required", "partial_text", "parser_error"}
    else:
        target_statuses = set(s.strip() for s in args.status_filter.split(","))

    targets = [r for r in manifest if r.get("status") in target_statuses]
    print(f"After status filter ({args.status_filter}): {len(targets)} books", file=sys.stderr)

    # Limit
    if args.limit:
        targets = targets[:args.limit]

    # Output paths
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pages_path = out_dir / "pages.jsonl"
    paragraphs_path = out_dir / "paragraphs.jsonl"
    books_path = out_dir / "books.jsonl"
    blocks_path = out_dir / "blocks.jsonl"

    # Load checkpoint: track (book_id, evidence_set_id) pairs + book_id-only set
    # Same book_id + same evidence_set_id = skip; different evidence_set_id = re-ingest (new version)
    processed_keys = set()  # set of (book_id, evidence_set_id) or legacy (book_id, "")
    processed_book_ids = set()  # book_id-only for fallback skip check
    if os.path.exists(args.checkpoint):
        with open(args.checkpoint, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("status") == "success":
                        bid = rec.get("book_id", "")
                        esid = rec.get("evidence_set_id", "")
                        processed_keys.add((bid, esid))
                        processed_book_ids.add(bid)
                except Exception:
                    pass
        print(f"Already processed (from checkpoint): {len(processed_book_ids)} books ({len(processed_keys)} book+evidence_set pairs)", file=sys.stderr)

    # Process
    total = len(targets)
    success_count = 0
    skip_count = 0
    error_count = 0
    start_time = time.time()

    for i, record in enumerate(targets):
        book_id = record["book_id"]
        status = record.get("status", "")
        artifact_id = record.get("artifact_id", "")
        pdf_path = resolve_pdf_path(record, args.base_dir)

        # Compute pre-emptive evidence_set_id for checkpoint skip check
        # Must match the version string used in _write_evidence / anchor_builder:
        #   pdfplumber@0.11.10:norm_v1  or  rapidocr_onnxruntime@1.4.0:norm_v1
        if status in ("text_extractable", "partial_text"):
            try:
                import pdfplumber
                _v = pdfplumber.__version__
            except Exception:
                _v = "0.0"
            extractor_ver = f"pdfplumber@{_v}"
        elif status == "ocr_required":
            try:
                import rapidocr_onnxruntime
                _v = getattr(rapidocr_onnxruntime, "__version__", "1.4.0")
            except Exception:
                _v = "1.4.0"
            extractor_ver = f"rapidocr_onnxruntime@{_v}"
        else:
            extractor_ver = "unknown"
        pre_evidence_set_id = ""
        if book_id and artifact_id:
            if "anchor_builder" not in sys.modules:
                sys.path.insert(0, str(Path(__file__).resolve().parent))
            from anchor_builder import make_evidence_set_id
            pre_evidence_set_id = make_evidence_set_id(book_id, artifact_id, f"{extractor_ver}:norm_v1")

        # Skip already ingested books.  Primary: exact (book_id, evidence_set_id)
        # match (supports re-ingest when extractor_version changes).  Fallback:
        # book_id-only — if this book_id was successfully completed before under
        # any evidence_set_id (or legacy empty), skip it.
        skip_key = (book_id, pre_evidence_set_id) if pre_evidence_set_id else (book_id, "")
        if skip_key in processed_keys or book_id in processed_book_ids:
            skip_count += 1
            continue

        # Header
        elapsed = time.time() - start_time
        eta_str = ""
        if success_count + error_count > 0:
            avg_per = elapsed / (success_count + error_count + skip_count + 1)
            remaining = avg_per * (total - i)
            eta_str = f", ETA {remaining/60:.1f}min"
        print(f"[{i+1}/{total}] {book_id} ({status}) {Path(pdf_path).name if pdf_path else 'NOT FOUND'}{eta_str}",
              file=sys.stderr, flush=True)

        if args.dry_run:
            append_checkpoint(args.checkpoint, {
                "book_id": book_id, "status": "dry_run",
                "timestamp": now_iso(),
            })
            continue

        if not pdf_path:
            append_checkpoint(args.checkpoint, {
                "book_id": book_id, "status": "error",
                "error": "PDF file not found",
                "timestamp": now_iso(),
            })
            error_count += 1
            continue

        try:
            result = _process_one_book(
                pdf_path, book_id, artifact_id, status, record,
                args.dpi, args.poppler_path, args.max_pages_per_book,
                onnx_threads=args.onnx_threads,
            )
            # Write Evidence records (returns evidence_set_id + row counts)
            write_info = _write_evidence(result, books_path, pages_path, paragraphs_path, blocks_path)

            append_checkpoint(args.checkpoint, {
                "book_id": book_id,
                "artifact_id": artifact_id,
                "evidence_set_id": write_info.get("evidence_set_id", ""),
                "extractor_sig": write_info.get("extractor_sig", ""),
                "normalization_version": write_info.get("normalization_version", ""),
                "status": "success",
                "pages": write_info.get("pages", 0),
                "paragraphs": write_info.get("paragraphs", 0),
                "books_records": write_info.get("books_records", 0),
                "text_pages": result.get("metadata", {}).get("text_extractable_pages", 0),
                "ocr_pages": result.get("metadata", {}).get("ocr_pages", 0),
                "mixed": result.get("metadata", {}).get("mixed", False),
                "timestamp": now_iso(),
            })
            success_count += 1

        except Exception as e:
            append_checkpoint(args.checkpoint, {
                "book_id": book_id, "status": "error",
                "error": f"{type(e).__name__}: {e}",
                "timestamp": now_iso(),
            })
            error_count += 1
            print(f"  ERROR: {e}", file=sys.stderr)

    # Summary
    total_time = time.time() - start_time
    print(f"\n=== Batch Complete ===", file=sys.stderr)
    print(f"Total: {total}, Success: {success_count}, Skipped: {skip_count}, Errors: {error_count}", file=sys.stderr)
    if success_count > 0:
        print(f"Time: {total_time:.1f}s ({total_time/success_count:.1f}s/book avg)", file=sys.stderr)
    else:
        print(f"Time: {total_time:.1f}s", file=sys.stderr)
    print(f"Checkpoint: {args.checkpoint}", file=sys.stderr)


def _process_one_book(pdf_path, book_id, artifact_id, status, record, dpi, poppler_path, max_pages, return_blocks=True, onnx_threads=2):
    """Dispatch to the right pipeline for one book. book_id always from manifest, never stem-derived."""
    if status in ("text_extractable", "partial_text"):
        from text_extract import extract_pdf_text
        return extract_pdf_text(
            pdf_path,
            book_id,
            status=status,
            dpi=dpi,
            ocr_fallback=True,
            poppler_path=poppler_path,
            max_pages=max_pages,
        )
    elif status == "ocr_required":
        from ocr_extract import process_pdf_ocr
        return process_pdf_ocr(
            pdf_path,
            book_id,
            dpi=dpi,
            max_pages=max_pages,
            poppler_path=poppler_path,
            return_blocks=return_blocks,
            onnx_threads=onnx_threads,
        )
    elif status == "parser_error":
        # Try OCR anyway — maybe it's just pdfplumber failing
        from ocr_extract import process_pdf_ocr
        return process_pdf_ocr(
            pdf_path,
            book_id,
            dpi=dpi,
            max_pages=max_pages,
            poppler_path=poppler_path,
            return_blocks=return_blocks,
            onnx_threads=onnx_threads,
        )
    else:
        raise ValueError(f"Unknown status: {status}")


def _split_paragraphs_geometry(blocks: list, text: str) -> list:
    """Split page text into paragraphs using block Y-coordinate gaps.

    Returns list of (char_start, char_end, para_text) tuples.
    Each block's char offset is approximated by its position in the text.
    """
    if not blocks or not text:
        return []
    # Build per-block char offsets by walking the text
    char_cursor = 0
    block_spans = []
    for blk in blocks:
        blk_text = blk.get("text", "")
        # Find this block's text in the normalized text starting from cursor
        idx = text.find(blk_text, char_cursor)
        if idx < 0:
            idx = char_cursor
        block_spans.append((idx, idx + len(blk_text), blk))
        char_cursor = idx + len(blk_text)

    # Compute Y-coordinate gaps between consecutive blocks
    # box format: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] — use top-y (y1) metric
    def block_top(blk):
        box = blk.get("box")
        if box and len(box) >= 2:
            return float(box[0][1])
        return 0.0
    def block_bottom(blk):
        box = blk.get("box")
        if box and len(box) >= 3:
            return float(box[2][1])
        return 0.0

    # Compute line heights and gaps
    heights = []
    for blk in blocks:
        h = block_bottom(blk) - block_top(blk)
        if h > 0:
            heights.append(h)
    if not heights:
        return []
    median_h = sorted(heights)[len(heights) // 2]
    para_gap = median_h * 1.8

    # Build paragraphs by grouping blocks with small Y gaps
    paragraphs = []
    para_start = 0
    prev_bottom = block_bottom(blocks[0])
    for i in range(1, len(blocks)):
        curr_top = block_top(blocks[i])
        gap = curr_top - prev_bottom
        if gap >= para_gap:
            # Emit paragraph [para_start, span_end)
            end_pos = block_spans[i - 1][1]
            para_text = text[para_start:end_pos].strip()
            if len(para_text) >= 10:
                paragraphs.append((para_start, end_pos, para_text))
            para_start = block_spans[i][0] if i < len(block_spans) else end_pos
        prev_bottom = max(prev_bottom, block_bottom(blocks[i]))

    # Final paragraph
    if para_start < len(text):
        para = text[para_start:].strip()
        if len(para) >= 10:
            paragraphs.append((para_start, len(text), para))
    return paragraphs


def _write_evidence(result, books_path, pages_path, paragraphs_path, blocks_path=None):
    """Convert extraction result to Evidence JSONL using anchor_builder.

    Returns dict with write info:
      - evidence_set_id
      - extractor_sig
      - normalization_version
      - pages: number of page records written
      - paragraphs: number of paragraph records written
      - books_records: number of book metadata records (0 or 1)
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from anchor_builder import (
        build_page_anchor, build_paragraph_anchor,
        make_evidence_set_id, compute_page_confidence, classify_block,
    )

    book_id = result.get("book_id", "")
    artifact_id = result.get("artifact_id", "")
    source_path = result.get("source_path", "")
    source_hash = artifact_id.replace("sha256:", "") if artifact_id.startswith("sha256:") else artifact_id
    extraction_meta = result.get("metadata", {})

    # Evidence set ID is deterministic: same book + artifact + extractor + norm_version = same set id
    # Re-running with same config is idempotent; upgrades produce a new set id.
    extractor_sig = extraction_meta.get("ocr_engine", extraction_meta.get("extractor", "mixed"))
    norm_ver = "norm_v1"
    evidence_set_id = make_evidence_set_id(book_id, artifact_id, f"{extractor_sig}:{norm_ver}")

    # --- Books record ---
    books_rec = {
        "type": "book_metadata",
        "book_id": book_id,
        "artifact_id": artifact_id,
        "source_path": source_path,
        "extractor": extractor_sig,
        "extractor_version": extractor_sig,
        "normalization_version": norm_ver,
        "total_pages": result.get("total_pages", 0),
        "processed_pages": result.get("processed_pages", 0),
        "source_hash": source_hash,
        "evidence_set_id": evidence_set_id,
        "ingested_at": now_iso(),
    }
    append_jsonl(books_path, books_rec)
    n_books = 1
    n_pages = 0
    n_paras = 0

    # --- Pages + Paragraphs + Blocks ---
    for page in result.get("pages", []):
        page_idx = page["page_index"]
        text_raw = page.get("text_raw", "")
        text_normalized = page.get("text_normalized", "")

        # Page-level evidence (evidence_set_id is the immutability boundary)
        page_anchor = build_page_anchor(
            book_id=book_id,
            artifact_id=artifact_id,
            source_hash=source_hash,
            page_index=page_idx,
            evidence_set_id=evidence_set_id,
            printed_page=page.get("printed_page", str(page_idx + 1)),
            text_raw=text_raw,
            text_normalized=text_normalized,
            normalization_version=page.get("normalization_version", "norm_v1"),
            extractor=page.get("extractor", "unknown"),
            extractor_version=page.get("extractor_version", "unknown"),
            confidence=page.get("confidence", 1.0),
            block_count=page.get("block_count", 0),
        )
        append_jsonl(pages_path, page_anchor)
        n_pages += 1

        # ── blocks.jsonl (bbox + confidence per block) ──────────────────────
        if blocks_path:
            for bi, blk in enumerate(page.get("blocks", [])):
                append_jsonl(blocks_path, {
                    "id": f"{book_id}:p{page_idx}:b{bi}:{evidence_set_id}",
                    "type": "block",
                    "book_id": book_id,
                    "artifact_id": artifact_id,
                    "source_hash": source_hash,
                    "page_index": page_idx,
                    "block_index": bi,
                    "text_raw": blk.get("text", ""),
                    "confidence": blk.get("confidence", 0.0),
                    "box": blk.get("box"),
                    "extractor": page.get("extractor", "unknown"),
                    "extractor_version": page.get("extractor_version", "unknown"),
                    "evidence_set_id": evidence_set_id,
                    "ingested_at": now_iso(),
                })

        # ── Paragraph-level evidence — geometry-based splitting ─────────────
        # Uses block Y-coordinate gaps to detect paragraph breaks.
        # Heuristic gap: ≥ 1.8× median line height within the page.
        if text_normalized:
            page_blocks = page.get("blocks", [])
            paragraphs = _split_paragraphs_geometry(page_blocks, text_normalized)
            # Fallback: single paragraph if no geometry available
            if not paragraphs:
                paragraphs = [(0, len(text_normalized), text_normalized)]

            para_idx = 0
            for (c_start, c_end, para_text) in paragraphs:
                para_text_stripped = para_text.strip()
                if len(para_text_stripped) < 10:
                    continue
                raw_chunk = text_raw[c_start:c_end] if c_end <= len(text_raw) else para_text_stripped
                para_anchor = build_paragraph_anchor(
                    book_id=book_id,
                    artifact_id=artifact_id,
                    source_hash=source_hash,
                    page_index=page_idx,
                    para_index=para_idx,
                    char_start=c_start,
                    char_end=c_end,
                    evidence_set_id=evidence_set_id,
                    page_id=page_anchor["id"],
                    text_raw=raw_chunk,
                    text_normalized=para_text_stripped,
                    normalization_version=page.get("normalization_version", "norm_v1"),
                    block_id="body",
                    extractor=page.get("extractor", "unknown"),
                    extractor_version=page.get("extractor_version", "unknown"),
                    confidence=page.get("confidence", 1.0),
                )
                append_jsonl(paragraphs_path, para_anchor)
                n_paras += 1
                para_idx += 1

    return {
        "evidence_set_id": evidence_set_id,
        "extractor_sig": extractor_sig,
        "normalization_version": norm_ver,
        "pages": n_pages,
        "paragraphs": n_paras,
        "books_records": n_books,
    }


if __name__ == "__main__":
    main()
