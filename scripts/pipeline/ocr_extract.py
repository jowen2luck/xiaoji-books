"""OCR Pipeline v2 — rasterize PDF pages and run RapidOCR.

Improvements over v1:
- Engine cached at module level (one RapidOCR instance per process).
- PyMuPDF renders pages directly — no per-page pdf2image/Poppler spawn.
- Returns block-level data (text + box + confidence) for downstream geometry.
- ONNX inter-op threads configurable via RapidOCR kwargs.

Output schema matches text_extract.extract_pdf_text() so the same
_evidence_writer can process both pipelines uniformly.

Page output fields now include:
    blocks: [{text, confidence, box}]  (for blocks.jsonl)

Usage:
    python ocr_extract.py --pdf ... --book-id ... [--dpi 200] [--max-pages N]
"""
import hashlib
import sys
import warnings
from pathlib import Path
from typing import Optional

import fitz

import rapidocr_onnxruntime

warnings.filterwarnings("ignore")

# ── Module-level engine cache (one per process) ──────────────────────────────
_OCR_ENGINE = None
_OCR_ENGINE_ARGS = None  # kwargs used to build the cached engine


def _get_ocr_engine(force: bool = False, onnx_threads: int = 2, **kwargs):
    """Return a cached RapidOCR instance (build once per process).

    Args:
        onnx_threads: intra-op threads for ONNX Runtime per sub-engine
                     (det/cls/rec). Default 2 (safe for 4 parallel workers).
        **kwargs: forwarded to RapidOCR constructor (det_*/cls_*/rec_*/Global).
    """
    global _OCR_ENGINE, _OCR_ENGINE_ARGS
    # Set per-subengine ONNX RapidOCR convention: det_/cls_/rec_ prefix
    kwargs.setdefault("det_intra_op_num_threads", onnx_threads)
    kwargs.setdefault("cls_intra_op_num_threads", onnx_threads)
    kwargs.setdefault("rec_intra_op_num_threads", onnx_threads)
    kwargs.setdefault("intra_op_num_threads", onnx_threads)
    if _OCR_ENGINE is not None and not force:
        return _OCR_ENGINE

    if _OCR_ENGINE is not None and _OCR_ENGINE_ARGS != kwargs:
        force = True

    if force and _OCR_ENGINE is not None:
        del _OCR_ENGINE
        _OCR_ENGINE = None

    if _OCR_ENGINE is None:
        _OCR_ENGINE = rapidocr_onnxruntime.RapidOCR(**kwargs)
        _OCR_ENGINE_ARGS = kwargs
    return _OCR_ENGINE


# ── Helpers ──────────────────────────────────────────────────────────────────

def compute_file_hash(file_path: str) -> str:
    """SHA-256 of file content."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ── Rendering: PyMuPDF (primary) + Poppler (fallback) ────────────────────────

def rasterize_page_pymupdf(doc: fitz.Document, page_idx: int, dpi: int = 200):
    """Render a single PDF page to PIL Image via PyMuPDF (no subprocess).

    doc is kept open by the caller.
    """
    from PIL import Image
    import io

    page = doc[page_idx]
    # scale = dpi / 72 (PDF native is 72 dpi)
    scale = dpi / 72.0
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    return Image.open(io.BytesIO(pix.tobytes("png")))


def rasterize_page_poppler(pdf_path: str, page_num: int, dpi: int = 200, poppler_path=None):
    """Fallback: render via pdf2image/Poppler (per-page subprocess)."""
    from pdf2image import convert_from_path
    kwargs = dict(first_page=page_num, last_page=page_num, dpi=dpi)
    if poppler_path:
        kwargs["poppler_path"] = poppler_path
    images = convert_from_path(pdf_path, **kwargs)
    return images[0]


def rasterize_page(pdf_path: str, doc: fitz.Document, page_idx: int,
                    dpi: int = 200, poppler_path=None):
    """Render a page via PyMuPDF; fall back to Poppler on error."""
    try:
        return rasterize_page_pymupdf(doc, page_idx, dpi)
    except Exception as e:
        # Fallback
        if doc:
            doc.close()
        doc = None  # noqa: F841
        return rasterize_page_poppler(pdf_path, page_idx + 1, dpi, poppler_path)


# ── OCR ──────────────────────────────────────────────────────────────────────

def ocr_image(ocr_engine, image) -> list:
    """Run RapidOCR on PIL Image. Returns list of {text, confidence, box}."""
    result, elapse = ocr_engine(image)
    blocks = []
    if result:
        for line in result:
            if len(line) >= 3:
                text = line[1]
                conf = line[2]
                box = line[0] if len(line) > 0 else None
                blocks.append({"text": text, "confidence": conf, "box": box})
    return blocks


# ── Main pipeline ────────────────────────────────────────────────────────────

def process_pdf_ocr(
    pdf_path: str,
    book_id: str,
    dpi: int = 200,
    max_pages: Optional[int] = None,
    poppler_path: Optional[str] = None,
    progress_cb=None,
    return_blocks: bool = False,
    onnx_threads: int = 2,
    _doc_handle: Optional[fitz.Document] = None,
) -> dict:
    """Full OCR pipeline for ocr_required PDFs.

    Engine is cached at module level — repeated calls within the same process
    reuse the same RapidOCR instance.

    Returns dict matching v1 schema; if return_blocks=True, also includes
    per-page block data (box + conf) for blocks.jsonl generation.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from normalizer import normalize_text

    pdf_path = str(Path(pdf_path).resolve())
    if not book_id:
        raise ValueError(f"process_pdf_ocr: book_id is required, got {book_id!r}")
    file_hash = compute_file_hash(pdf_path)
    artifact_id = f"sha256:{file_hash}"

    # Re-uses cached engine
    ocr_engine = _get_ocr_engine(onnx_threads=onnx_threads)
    ocr_ver = getattr(rapidocr_onnxruntime, "__version__", "unknown")

    # Use caller-provided doc handle or open fresh
    own_doc = _doc_handle is None
    doc = _doc_handle if _doc_handle is not None else fitz.open(pdf_path)
    try:
        total_pages = doc.page_count
        pages_to_process = min(total_pages, max_pages) if max_pages else total_pages
        print(f"  PDF: {Path(pdf_path).name}, {total_pages}pages, processing {pages_to_process}",
              file=sys.stderr)

        pages = []
        for i in range(pages_to_process):
            img = rasterize_page(pdf_path, doc, page_idx=i, dpi=dpi, poppler_path=poppler_path)
            blocks = ocr_image(ocr_engine, img)
            avg_conf = sum(b["confidence"] for b in blocks) / len(blocks) if blocks else 0.0

            text_raw = "\n".join(b["text"] for b in blocks)
            text_normalized, norm_ver, applied = normalize_text(text_raw)

            page_rec = {
                "page_index": i,
                "printed_page": str(i + 1),
                "text_raw": text_raw,
                "text_normalized": text_normalized,
                "normalization_version": norm_ver,
                "extractor": "rapidocr_onnxruntime",
                "extractor_version": ocr_ver,
                "confidence": round(avg_conf, 4),
                "ocr_fallback_used": False,
                "block_count": len(blocks),
                "normalization_applied": applied,
            }
            if return_blocks:
                page_rec["blocks"] = blocks
            pages.append(page_rec)

            if progress_cb:
                progress_cb(i + 1, pages_to_process, "ocr")
    finally:
        if own_doc:
            doc.close()

    return {
        "book_id": book_id,
        "source_path": str(Path(pdf_path)),
        "artifact_id": artifact_id,
        "total_pages": total_pages,
        "processed_pages": pages_to_process,
        "pages": pages,
        "metadata": {
            "ocr_engine": "rapidocr_onnxruntime",
            "ocr_version": ocr_ver,
            "dpi": dpi,
            "status": "ocr_required",
        },
    }


# ── CLI smoke test ────────────────────────────────────────────────────────────

def main():
    parser = __import__("argparse").ArgumentParser(description="OCR pipeline v2")
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--book-id", required=True,
                        help="Stable book_id from manifest")
    parser.add_argument("--output", default="data/evidence/ocr_smoke_output.json")
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--poppler-path", default=None)
    parser.add_argument("--onnx-threads", type=int, default=2,
                        help="ONNX intra-op threads per sub-engine (default 2)")
    args = parser.parse_args()

    def progress(p, total, mode):
        print(f"  Page {p}/{total} [{mode}]", file=sys.stderr, end="\r")

    if not args.book_id:
        parser.error("--book-id is required (book_id must come from manifest)")

    result = process_pdf_ocr(
        args.pdf,
        args.book_id,
        dpi=args.dpi,
        max_pages=args.max_pages,
        poppler_path=args.poppler_path,
        progress_cb=progress,
        onnx_threads=args.onnx_threads,
    )

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\nWrote {args.output}", file=sys.stderr)
    if result["pages"]:
        p0 = result["pages"][0]
        print(f"\nPage 1 ({p0['block_count']} blocks, conf={p0['confidence']}):", file=sys.stderr)
        print(f"  {p0['text_normalized'][:200]}", file=sys.stderr)


if __name__ == "__main__":
    import json
    main()
