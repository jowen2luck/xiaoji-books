"""Anchor Builder — construct Evidence record anchors.

Outputs page-level and paragraph-level Anchor records that comply with
SKILL.md §3.1 evidence schema.

Anchors are immutable once created: they encode the physical location
(text bounds, page, bbox) within the version of the source file
identified by the artifact_id (SHA-256).
"""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_evidence_set_id(book_id: str, artifact_id: str, extractor_version: str) -> str:
    """Deterministic evidence_set_id from book + artifact + extractor version.

    Re-running the same extractor on the same file yields the same set id;
    upgrading the extractor version produces a new set id.
    """
    seed = f"{book_id}:{artifact_id}:{extractor_version}"
    h = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"es-{h}"


def build_page_anchor(
    book_id: str,
    artifact_id: str,
    source_hash: str,
    page_index: int,
    evidence_set_id: str = "",
    printed_page: Optional[str] = None,
    text_raw: str = "",
    text_normalized: str = "",
    normalization_version: str = "norm_v1",
    extractor: str = "unknown",
    extractor_version: str = "0.0",
    confidence: float = 0.0,
    block_count: int = 0,
) -> dict:
    """Build a single page-level Evidence record.

    Args:
        book_id: stable book identifier (from manifest)
        artifact_id: SHA-256 of source file
        source_hash: SHA-256 of source file (redundant with artifact_id but explicit)
        page_index: 0-based page number
        printed_page: human-readable page label (from PDF)
        text_raw: original extraction output
        text_normalized: after normalization
        normalization_version: e.g. "norm_v1"
        extractor: e.g. "pdfplumber@0.11.10", "rapidocr_onnxruntime@1.4.0"
        extractor_version: semantic version
        confidence: average page confidence (OCR) or 1.0 (text extract)
        block_count: number of layout blocks recognized
    """
    # ID MUST include evidence_set_id so re-ingestion with new version
    # produces a new ID and doesn't overwrite previous Evidence (immutable principle)
    if evidence_set_id:
        page_id = f"{book_id}:p{page_index}:{evidence_set_id}"
    else:
        # Legacy fallback (not recommended for production)
        page_id = f"{book_id}:p{page_index}"
    
    return {
        "id": page_id,
        "type": "page",
        "book_id": book_id,
        "artifact_id": artifact_id,
        "source_hash": source_hash,
        "page_index": page_index,
        "printed_page": printed_page if printed_page is not None else str(page_index + 1),
        "block_id": None,
        "char_range": None,
        "layout_bbox": None,
        "text_raw": text_raw,
        "text_normalized": text_normalized,
        "normalization_version": normalization_version,
        "extractor": extractor,
        "extractor_version": extractor_version,
        "confidence": confidence,
        "block_count": block_count,
        "ingested_at": _now_iso(),
        "evidence_set_id": evidence_set_id,
        "previous_set_id": None,
    }


def build_paragraph_anchor(
    book_id: str,
    artifact_id: str,
    source_hash: str,
    page_index: int,
    para_index: int,
    char_start: int,
    char_end: int,
    evidence_set_id: str = "",
    page_id: str = "",
    text_raw: str = "",
    text_normalized: str = "",
    normalization_version: str = "norm_v1",
    block_id: str = "body",
    layout_bbox: Optional[list] = None,
    printed_page: Optional[str] = None,
    extractor: str = "unknown",
    extractor_version: str = "0.0",
    confidence: float = 0.0,
) -> dict:
    """Build a single paragraph-level Evidence record.

    Args:
        para_index: paragraph index within the page (0-based)
        char_start: start offset in text_normalized
        char_end: end offset (exclusive) in text_normalized
        block_id: layout classification (heading, body, caption, etc.)
        layout_bbox: OCR bounding box [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
    """
    # ID MUST include evidence_set_id so re-ingestion with new version
    # produces a new ID and doesn't overwrite previous Evidence
    if evidence_set_id:
        para_id = f"{book_id}:p{page_index}:para{para_index}:{evidence_set_id}"
    else:
        # Legacy fallback (not recommended)
        para_id = f"{book_id}:p{page_index}:para{para_index}"
    
    return {
        "id": para_id,
        "type": "paragraph",
        "book_id": book_id,
        "artifact_id": artifact_id,
        "source_hash": source_hash,
        "page_id": page_id,
        "page_index": page_index,
        "printed_page": printed_page if printed_page is not None else str(page_index + 1),
        "block_id": block_id,
        "char_range": [char_start, char_end],
        "layout_bbox": layout_bbox,
        "text_raw": text_raw,
        "text_normalized": text_normalized,
        "normalization_version": normalization_version,
        "extractor": extractor,
        "extractor_version": extractor_version,
        "confidence": confidence,
        "ingested_at": _now_iso(),
        "evidence_set_id": evidence_set_id,
        "previous_set_id": None,
    }


def compute_page_confidence(blocks: list) -> float:
    """Average confidence across OCR blocks in a page."""
    if not blocks:
        return 0.0
    confs = [b.get("confidence", 0.0) for b in blocks if b.get("confidence") is not None]
    if not confs:
        return 0.0
    return round(sum(confs) / len(confs), 4)


def classify_block(block_text: str, block_box: list = None) -> str:
    """Simple heuristic block classification.

    - heading: short line (<= 40 chars), all caps or starts with numbering
    - body: regular paragraph
    - caption: starts with "图" or "表" prefix
    """
    if not block_text:
        return "body"
    text = block_text.strip()
    if len(text) <= 40:
        if text[:1].isdigit() or text.startswith(("第", "图", "表")):
            if "章" in text or "节" in text or "、" in text[:5]:
                return "heading"
        if text.startswith(("图", "表")):
            return "caption"
    return "body"


if __name__ == "__main__":
    # Quick self-test
    print("Anchor builder self-test:")
    p = build_page_anchor(
        book_id="book-test01",
        artifact_id="sha256:abc123",
        source_hash="sha256:abc123",
        page_index=0,
        printed_page="i",
        text_raw="first page text",
        text_normalized="first page text",
        extractor="pdfplumber@0.11.10",
        extractor_version="0.11.10",
        confidence=1.0,
    )
    print(f"  page: id={p['id']}, es={p['evidence_set_id']}")
    
    para = build_paragraph_anchor(
        book_id="book-test01",
        artifact_id="sha256:abc123",
        source_hash="sha256:abc123",
        page_index=0,
        para_index=0,
        char_start=0,
        char_end=15,
        text_raw="first page text",
        text_normalized="first page text",
        block_id="body",
        extractor="pdfplumber@0.11.10",
        extractor_version="0.11.10",
        confidence=1.0,
    )
    print(f"  para: id={para['id']}, char_range={para['char_range']}")
    
    # different extractor version → different evidence set id
    p2 = build_page_anchor(
        book_id="book-test01",
        artifact_id="sha256:abc123",
        source_hash="sha256:abc123",
        page_index=0,
        extractor="pdfplumber@0.11.11",
        extractor_version="0.11.11",
    )
    assert p["evidence_set_id"] != p2["evidence_set_id"], "es_id should change with extractor"
    print("  extractor version change: evidence_set_id differs ✓")
    
    # same inputs → same evidence set id
    p3 = build_page_anchor(
        book_id="book-test01",
        artifact_id="sha256:abc123",
        source_hash="sha256:abc123",
        page_index=0,
        extractor="pdfplumber@0.11.10",
        extractor_version="0.11.10",
    )
    assert p["evidence_set_id"] == p3["evidence_set_id"], "es_id should be deterministic"
    print("  deterministic evidence_set_id ✓")
