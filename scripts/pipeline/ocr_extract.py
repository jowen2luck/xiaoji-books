"""OCR Pipeline — rasterize PDF pages and run RapidOCR.

Output schema matches text_extract.extract_pdf_text() so the same
_evidence_writer can process both pipelines uniformly.

Output format:
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
                "extractor": "rapidocr_onnxruntime",
                "extractor_version": "1.4.0",
                "confidence": 0.95,
                "ocr_fallback_used": False,
                "block_count": 25,
                "normalization_applied": ["fullwidth_to_halfwidth", ...],
            }
        ],
        "metadata": {
            "ocr_engine": "rapidocr_onnxruntime",
            "ocr_version": "...",
            "dpi": 200,
            "status": "ocr_required",
        }
    }
"""
import hashlib
import sys
import warnings
from pathlib import Path
from typing import Optional

import fitz
from pdf2image import convert_from_path
from PIL import Image

import rapidocr_onnxruntime

warnings.filterwarnings("ignore")


def compute_file_hash(file_path: str) -> str:
    """SHA-256 of file content."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def rasterize_page(pdf_path: str, page_num: int, dpi: int = 200, poppler_path: str = None) -> Image.Image:
    """Convert single PDF page to PIL Image."""
    kwargs = dict(first_page=page_num, last_page=page_num, dpi=dpi)
    if poppler_path:
        kwargs["poppler_path"] = poppler_path
    images = convert_from_path(pdf_path, **kwargs)
    return images[0]


def ocr_image(ocr_engine, image: Image.Image) -> list:
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


def process_pdf_ocr(
    pdf_path: str,
    book_id: str,
    dpi: int = 200,
    max_pages: Optional[int] = None,
    poppler_path: Optional[str] = None,
    progress_cb=None,
) -> dict:
    """Full OCR pipeline for ocr_required PDFs.

    Uses RapidOCR (ONNX Runtime) — compatible with PaddleOCR's API
    but avoids the oneDNN CPU incompatibility that blocks PaddleOCR 3.x.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from normalizer import normalize_text

    pdf_path = str(Path(pdf_path).resolve())
    if not book_id:
        raise ValueError(f"process_pdf_ocr: book_id is required, got {book_id!r}")
    # book_id is taken from manifest ONLY — never derive from filename
    file_hash = compute_file_hash(pdf_path)
    artifact_id = f"sha256:{file_hash}"

    print(f"  Init RapidOCR engine...", file=sys.stderr)
    ocr_engine = rapidocr_onnxruntime.RapidOCR()
    ocr_ver = getattr(rapidocr_onnxruntime, "__version__", "unknown")

    doc = fitz.open(pdf_path)
    total_pages = doc.page_count
    doc.close()

    pages_to_process = min(total_pages, max_pages) if max_pages else total_pages
    print(f"  PDF: {Path(pdf_path).name}, {total_pages} pages total, processing {pages_to_process}",
          file=sys.stderr)

    pages = []
    for i in range(pages_to_process):
        page_label = i + 1
        img = rasterize_page(pdf_path, page_num=page_label, dpi=dpi, poppler_path=poppler_path)
        blocks = ocr_image(ocr_engine, img)
        avg_conf = sum(b["confidence"] for b in blocks) / len(blocks) if blocks else 0.0

        # Join all block text into a single page text
        text_raw = "\n".join(b["text"] for b in blocks)
        text_normalized, norm_ver, applied = normalize_text(text_raw)

        pages.append({
            "page_index": i,
            "printed_page": str(page_label),
            "text_raw": text_raw,
            "text_normalized": text_normalized,
            "normalization_version": norm_ver,
            "extractor": "rapidocr_onnxruntime",
            "extractor_version": ocr_ver,
            "confidence": round(avg_conf, 4),
            "ocr_fallback_used": False,
            "block_count": len(blocks),
            "normalization_applied": applied,
        })

        if progress_cb:
            progress_cb(i + 1, pages_to_process, "ocr")

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


def main():
    parser = __import__("argparse").ArgumentParser(description="OCR pipeline")
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--book-id", required=True, help="Stable book_id from manifest")
    parser.add_argument("--output", default="data/evidence/ocr_smoke_output.json")
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--poppler-path", default=None)
    args = parser.parse_args()

    def progress(p, total, mode):
        print(f"  Page {p}/{total} [{mode}]", file=sys.stderr, end="\r")

    print(f"=== OCR Smoke: {args.pdf} ===", file=sys.stderr)
    if not args.book_id:
        parser.error("--book-id is required (book_id must come from manifest)")
    result = process_pdf_ocr(
        args.pdf,
        args.book_id,
        dpi=args.dpi,
        max_pages=args.max_pages,
        poppler_path=args.poppler_path,
        progress_cb=progress,
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
