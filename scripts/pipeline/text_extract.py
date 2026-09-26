"""Text Extraction Pipeline — handles text_extractable and partial_text PDFs.

For `text_extractable` status: extract text directly using pdfplumber.
For `partial_text` status: try pdfplumber first on each page; if a page
yields insufficient text (e.g. < 50 chars), fall back to OCR for that page.

Returns structured page-level records with raw text, normalized text,
confidence, and extractor provenance. Feed the output into
`anchor_builder` to produce final Evidence records.
"""
import hashlib
import io
import sys
import warnings
from pathlib import Path
from typing import Optional

# Per-page timeout in seconds — pdfplumber can hang on malformed PDFs
PAGE_TIMEOUT = 90

# Max time we wait for the pdfplumber child process regardless of page count
MAX_PDFPLUMBER_WAIT = 180

import fitz  # PyMuPDF

# Suppress pdfplumber stderr noise
warnings.filterwarnings("ignore")

# Optional imports — lazy loaded
_pdfplumber = None
_rapidocr_engine = None


def _get_ocr_engine():
    global _rapidocr_engine
    if _rapidocr_engine is None:
        import rapidocr_onnxruntime
        _rapidocr_engine = rapidocr_onnxruntime.RapidOCR()
    return _rapidocr_engine


def compute_sha256(file_path: str) -> str:
    """SHA-256 of file content."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def get_page_count(pdf_path: str) -> int:
    """Get total page count using PyMuPDF."""
    doc = fitz.open(pdf_path)
    count = doc.page_count
    doc.close()
    return count


def _pdfplumber_worker_loop(pdf_path: str, page_indices: list, result_queue):
    """Child-process worker: opens PDF once, extracts pages, pushes results."""
    import importlib.metadata
    import pdfplumber
    try:
        _ver = importlib.metadata.version("pdfplumber")
    except Exception:
        _ver = "unknown"
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for idx in page_indices:
                if idx >= len(pdf.pages):
                    result_queue.put((idx, "", f"pdfplumber@{_ver}", 0.0))
                    continue
                page = pdf.pages[idx]
                text = page.extract_text() or ""
                result_queue.put((idx, text.strip(), f"pdfplumber@{_ver}", 1.0))
    except Exception as e:
        # Push error for remaining pages
        for idx in page_indices:
            result_queue.put((idx, "", f"pdfplumber@error:{type(e).__name__}", 0.0))
    finally:
        # Sentinel to signal completion
        result_queue.put(None)


def extract_pages_pdfplumber(pdf_path: str, page_indices: list, timeout: int = None) -> dict:
    """Extract multiple pages via pdfplumber in a single child process.

    Returns dict mapping page_index -> (text, extractor, confidence).
    Pages that weren't returned before timeout are filled with error entries.
    """
    import threading
    from multiprocessing import Process, Queue

    timeout = timeout or min(PAGE_TIMEOUT * len(page_indices) + 60, 300)
    q = Queue()
    p = Process(target=_pdfplumber_worker_loop, args=(pdf_path, page_indices, q), daemon=True)
    p.start()

    # Drain queue in a thread to avoid worker deadlock on full queue
    results = {}
    sentinel_received = threading.Event()

    def _drain():
        while True:
            try:
                item = q.get(timeout=1.0)
                if item is None:
                    sentinel_received.set()
                    return
                idx, text, ext, conf = item
                results[idx] = (text, ext, conf)
            except Exception:
                if not p.is_alive():
                    return

    drain_thread = threading.Thread(target=_drain, daemon=True)
    drain_thread.start()

    p.join(timeout=timeout)
    drain_thread.join(timeout=10)

    if p.is_alive():
        p.kill()
        p.join(timeout=5)
        # Final drain
        while not q.empty():
            try:
                item = q.get_nowait()
                if item is None:
                    break
                idx, text, ext, conf = item
                results[idx] = (text, ext, conf)
            except Exception:
                break

    # Mark missing pages
    for idx in page_indices:
        if idx not in results:
            results[idx] = ("", f"pdfplumber@timeout:{timeout}s", 0.0)
    return results


def extract_page_text(pdf_path: str, page_index: int) -> tuple:
    """Single-page wrapper — uses the batched pdfplumber child-process approach."""
    results = extract_pages_pdfplumber(pdf_path, [page_index])
    return results.get(page_index, ("", "pdfplumber@error:missing", 0.0))


def ocr_page(pdf_path: str, page_index: int, dpi: int = 200, poppler_path: str = None) -> tuple:
    """OCR a single PDF page using RapidOCR.

    Rendering priority:
      1. PyMuPDF (fitz) — no external poppler needed
      2. pdf2image + poppler fallback (when poppler_path is given)

    Returns (text, avg_confidence, block_count).
    """
    engine = _get_ocr_engine()

    # Try PyMuPDF rendering first (no poppler dependency)
    image = _render_page_pymupdf(pdf_path, page_index, dpi)

    if image is None:
        # Fallback to pdf2image if poppler available
        try:
            from pdf2image import convert_from_path
            page_num = page_index + 1
            kwargs = dict(first_page=page_num, last_page=page_num, dpi=dpi)
            if poppler_path:
                kwargs["poppler_path"] = poppler_path
            images = convert_from_path(pdf_path, **kwargs)
            if not images:
                return "", 0.0, 0
            image = images[0]
        except Exception:
            return "", 0.0, 0

    result, elapse = engine(image)

    if not result:
        return "", 0.0, 0

    texts = []
    confs = []
    for line in result:
        if len(line) >= 3:
            texts.append(line[1])
            confs.append(line[2])

    text = "\n".join(texts)
    avg_conf = sum(confs) / len(confs) if confs else 0.0
    return text.strip(), round(avg_conf, 4), len(texts)


def _render_page_pymupdf(pdf_path: str, page_index: int, dpi: int = 200):
    """Render a PDF page to PIL Image using PyMuPDF (no poppler needed)."""
    try:
        from PIL import Image
        doc = fitz.open(pdf_path)
        if page_index >= doc.page_count:
            doc.close()
            return None
        page = doc.load_page(page_index)
        # Scale factor: PDF base DPI is 72, so scale = dpi / 72
        scale = dpi / 72.0
        mat = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        doc.close()
        return img
    except Exception:
        return None


_LABEL_PATTERNS = None

def _get_label_patterns():
    """Compiled regex patterns for label-only lines (cached)."""
    global _LABEL_PATTERNS
    if _LABEL_PATTERNS is None:
        import re
        _LABEL_PATTERNS = [
            re.compile(r'^\s*[\w\-]+\s*$'),               # single identifier
            re.compile(r'^\s*\d+\s*$'),                   # just a page number
            re.compile(r'^\s*第\s*\d+\s*页?\s*$'),        # "第X页"
            re.compile(r'^\s*Page\s+\d+\s*$', re.I),     # "Page X"
            re.compile(r'^\s*www\.\S+\s*$'),             # URL
            re.compile(r'^\s*https?://\S+\s*$'),         # URL
            re.compile(r'^\s*[\u4e00-\u9fff]\s*$'),      # single CJK char
        ]
    return _LABEL_PATTERNS


def _count_meaningful_lines(text: str) -> int:
    """Count lines with actual content (skip labels/numbers/URLs)."""
    patterns = _get_label_patterns()
    meaningful = 0
    for line in text.split('\n'):
        s = line.strip()
        if not s or len(s) < 5:
            continue
        if any(p.match(s) for p in patterns):
            continue
        meaningful += 1
    return meaningful


def is_page_text_sufficient(text: str, min_chars: int = 50) -> bool:
    """Smart heuristic: does extracted text contain meaningful content?

    Uses multi-factor content quality scoring instead of simple char count.
    Requires: CJK chars >= 30 OR meaningful_lines >= 3 with avg_line_len >= 15.
    """
    import re
    if not text or not text.strip():
        return False

    total_chars = len(text.strip())
    cjk_chars = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf]', text))
    lines = [l for l in text.split('\n') if l.strip()]
    meaningful_lines = _count_meaningful_lines(text)
    avg_line_len = total_chars / max(len(lines), 1)

    # Weighted score (matches diagnose_content_quality.py logic)
    score = 0.0
    score += min(cjk_chars / 30.0, 3.0) * 2.0
    score += min(total_chars / 80.0, 3.0) * 1.0
    score += min(meaningful_lines / 3.0, 3.0) * 1.5
    score += min(avg_line_len / 15.0, 2.0) * 0.5

    if score < 0:
        score = 0.0

    # Accept if score >= 3.0 AND has either CJK content or multiple meaningful lines
    return score >= 3.0 and (cjk_chars >= 30 or (meaningful_lines >= 3 and avg_line_len >= 15))


def extract_pdf_text(
    pdf_path: str,
    book_id: str,
    status: str = "text_extractable",
    dpi: int = 200,
    ocr_fallback: bool = True,
    min_text_chars: int = 50,
    poppler_path: str = None,
    max_pages: Optional[int] = None,
    progress_cb=None,
) -> dict:
    """Extract text from a PDF with optional per-page OCR fallback.

    Args:
        pdf_path: path to the PDF file
        status: 'text_extractable' or 'partial_text' (from manifest)
        dpi: OCR rasterization DPI
        ocr_fallback: if True, OCR pages where pdfplumber yields little text
        min_text_chars: threshold for "insufficient text" per page
        poppler_path: path to poppler bin directory
        max_pages: limit pages processed (for smoke tests)
        progress_cb: callback(page_index, total_pages, status_str)

    Returns:
        {
            "book_id": "...",
            "source_path": "...",
            "artifact_id": "sha256:...",
            "total_pages": N,
            "processed_pages": M,
            "pages": [
                {
                    "page_index": 0,
                    "printed_page": "1",
                    "text_raw": "...",
                    "text_normalized": "...",
                    "normalization_version": "norm_v1",
                    "extractor": "pdfplumber" | "rapidocr_onnxruntime",
                    "extractor_version": "0.11.10",
                    "confidence": 0.95,
                    "ocr_fallback_used": False,
                    "block_count": 25,
                }
            ],
            "metadata": {
                "text_extractable_pages": N1,
                "ocr_pages": N2,
                "mixed": True/False,
            }
        }
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from normalizer import normalize_text

    pdf_path = str(Path(pdf_path).resolve())
    file_hash = compute_sha256(pdf_path)
    artifact_id = f"sha256:{file_hash}"

    doc = fitz.open(pdf_path)
    total_pages = doc.page_count
    # Extract page labels if available
    page_labels = {}
    try:
        for i in range(total_pages):
            label = doc.get_page_labels(i) if hasattr(doc, "get_page_labels") else None
    except Exception:
        label = None
    doc.close()

    pages_to = min(total_pages, max_pages) if max_pages else total_pages

    pages = []
    text_count = 0
    ocr_count = 0

    # If status is text_extractable, skip OCR fallback
    use_ocr_fallback = ocr_fallback

    # Tier 1: PyMuPDF (fast, never hangs) — extract all pages
    fitz_doc = fitz.open(pdf_path)
    fitz_texts = {}
    for i in range(pages_to):
        try:
            page = fitz_doc.load_page(i)
            fitz_texts[i] = (page.get_text("text").strip(), "pymupdf@fitz", 1.0)
        except Exception:
            fitz_texts[i] = ("", "pymupdf@fitz_error", 0.0)
    fitz_doc.close()

    # Identify hard pages where fitz returns insufficient text
    hard_pages = [i for i in range(pages_to)
                  if not is_page_text_sufficient(fitz_texts[i][0], min_text_chars)]

    # Tier 2: pdfplumber in child process — only for hard pages (with cap)
    pdfplumber_results = {}
    if hard_pages:
        pdfplumber_results = extract_pages_pdfplumber(
            pdf_path, hard_pages, timeout=MAX_PDFPLUMBER_WAIT
        )

    # Compose final page records
    for i in range(pages_to):
        page_label = str(i + 1)
        ocr_fallback_used = False
        block_count = 0

        # Best available text: prefer pdfplumber if it produced good output
        pb = pdfplumber_results.get(i)
        fitz_text, fitz_ext, fitz_conf = fitz_texts[i]

        if pb and is_page_text_sufficient(pb[0], min_text_chars):
            text_raw, extractor, conf = pb
        else:
            text_raw, extractor, conf = fitz_text, fitz_ext, fitz_conf

        if use_ocr_fallback and not is_page_text_sufficient(text_raw, min_text_chars):
            # Tier 3: OCR for this page
            text_raw, conf, block_count = ocr_page(
                pdf_path, i, dpi=dpi, poppler_path=poppler_path
            )
            extractor = "rapidocr_onnxruntime"
            ocr_fallback_used = True
            ocr_count += 1
        elif extractor.startswith(("pdfplumber", "pymupdf")):
            text_count += 1

        text_normalized, norm_ver, applied = normalize_text(text_raw)

        page_rec = {
            "page_index": i,
            "printed_page": page_label,
            "text_raw": text_raw,
            "text_normalized": text_normalized,
            "normalization_version": norm_ver,
            "extractor": extractor,
            "extractor_version": extractor.split("@")[-1] if "@" in extractor else "unknown",
            "confidence": conf,
            "ocr_fallback_used": ocr_fallback_used,
            "block_count": block_count if ocr_fallback_used else 0,
            "normalization_applied": applied,
        }
        pages.append(page_rec)

        if progress_cb:
            progress_cb(i + 1, pages_to,
                       "ocr" if ocr_fallback_used else "text")

    if not book_id:
        raise ValueError(f"extract_pdf_text: book_id is required, got {book_id!r}")
    return {
        "book_id": book_id,
        "source_path": str(Path(pdf_path)),
        "artifact_id": artifact_id,
        "total_pages": total_pages,
        "processed_pages": pages_to,
        "pages": pages,
        "metadata": {
            "text_extractable_pages": text_count,
            "ocr_pages": ocr_count,
            "mixed": text_count > 0 and ocr_count > 0,
            "status": status,
        },
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Text extract pipeline (with per-page OCR fallback)")
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--book-id", required=True, help="Stable book_id from manifest")
    parser.add_argument("--output", default="data/evidence/text_extract_output.json")
    parser.add_argument("--status", default="text_extractable",
                       choices=["text_extractable", "partial_text"])
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--no-ocr-fallback", action="store_true")
    parser.add_argument("--poppler-path", default=None)
    args = parser.parse_args()

    def progress(p, total, mode):
        print(f"  Page {p}/{total} [{mode}]", file=sys.stderr, end="\r")

    print(f"=== TextExtract: {args.pdf} ===", file=sys.stderr)
    print(f"status={args.status}, ocr_fallback={not args.no_ocr_fallback}", file=sys.stderr)

    if not args.book_id:
        parser.error("--book-id is required (book_id must come from manifest)")
    result = extract_pdf_text(
        args.pdf,
        args.book_id,
        status=args.status,
        dpi=args.dpi,
        ocr_fallback=not args.no_ocr_fallback,
        poppler_path=args.poppler_path,
        max_pages=args.max_pages,
        progress_cb=progress,
    )

    import json
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\nWrote {args.output}", file=sys.stderr)
    print(f"Pages: text={result['metadata']['text_extractable_pages']}, "
          f"ocr_fallback={result['metadata']['ocr_pages']}", file=sys.stderr)
    
    if result["pages"]:
        p0 = result["pages"][0]
        print(f"\nPage 1 extract (first 200 chars):", file=sys.stderr)
        print(f"  [{p0['extractor']}] {p0['text_normalized'][:200]}", file=sys.stderr)


if __name__ == "__main__":
    main()
