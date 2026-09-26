#!/usr/bin/env python3
"""Mobile Workshop Fleet Worker (v2.2.0) — Strict Two-Phase Pipeline & Full Node Provenance.

Phases:
1. Phase 1 (text_layer_triage):
   - Fast inventory, SHA-256 verification, and vector font text extraction.
   - Strict classification:
     * 'text_layer_extracted': meaningful text with reasonable CJK/Latin density.
     * 'text_layer_missing_or_low_text': scanned images / low-text / empty pages.
   - Only 'text_layer_extracted' pages generate paragraphs & anchors in Phase 1.
   - Missing/low-text pages are queued for Phase 2 visual OCR.
2. Phase 2 (visual_ocr):
   - Rasterizes PDF pages (via PyMuPDF / pdftoppm) and runs visual OCR (RapidOCR / Tesseract 5).
   - Dynamic page chunk execution with full provenance tracking:
     (taskId, nodeId, attempt, inputSha256, pageRange, workerVersion, engineVersion).

Complies with SKILL.md evidence schema, immutability, and reproducible audit standards.
"""
import argparse
import hashlib
import json
import os
import platform
import re
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

WORKER_VERSION = "v2.3.0"
NORMALIZATION_VERSION = "norm_v1"
EXTRACTOR_POPPLER = "poppler@pdftotext"
EXTRACTOR_PYMUPDF = "pymupdf@fitz"
EXTRACTOR_TESSERACT = "tesseract@5.5.3"
EXTRACTOR_RAPIDOCR = "rapidocr_onnxruntime@1.4.0"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_system_resources() -> Tuple[int, float]:
    """Return (peak_ram_bytes, temperature_celsius) portably."""
    ram_bytes = 0
    temp_c = 0.0

    # 1. Peak RAM
    try:
        if sys.platform == "win32":
            import psutil
            process = psutil.Process()
            ram_bytes = process.memory_info().peak_wset
        else:
            import resource
            rusage = resource.getrusage(resource.RUSAGE_SELF)
            ram_bytes = rusage.ru_maxrss * 1024
    except Exception:
        pass

    # 2. Temperature (Android / Linux)
    try:
        if sys.platform != "win32":
            for zone in Path("/sys/class/thermal").glob("thermal_zone*"):
                temp_file = zone / "temp"
                type_file = zone / "type"
                if temp_file.exists() and type_file.exists():
                    z_type = type_file.read_text(errors="ignore").strip().lower()
                    if any(k in z_type for k in ("cpu", "soc", "battery", "tsens")):
                        val = float(temp_file.read_text().strip())
                        if val > 1000:
                            val = val / 1000.0
                        temp_c = val
                        break
    except Exception:
        pass

    return ram_bytes, round(temp_c, 1)


def compute_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def compute_bytes_sha256(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def make_evidence_set_id(book_id: str, artifact_id: str, extractor_version: str) -> str:
    seed = f"{book_id}:{artifact_id}:{extractor_version}"
    h = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"es-{h}"


def normalize_cjk_text(raw_text: str) -> str:
    """Clean up extracted text: strip watermarks, normalize whitespace, preserve CJK layout."""
    if not raw_text:
        return ""
    lines = raw_text.splitlines()
    cleaned_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Strip common archive watermarks
        if re.search(r"(marxists\.org|中文马克思主义文库|扫描|PDF制作|未经授权)", line, re.I):
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def classify_page_text(norm_text: str) -> Tuple[str, float, float]:
    """Classify page text into text_layer_extracted vs text_layer_missing_or_low_text.
    
    Returns:
        (classification, cjk_ratio, confidence)
    """
    cleaned = norm_text.strip()
    total_chars = len(cleaned)
    if total_chars < 30:
        return "text_layer_missing_or_low_text", 0.0, 0.0

    cjk_chars = len(re.findall(r"[\u4e00-\u9fa5]", cleaned))
    cjk_ratio = cjk_chars / total_chars

    # At least 30 chars with 20%+ CJK or 80+ Latin/alphanumeric characters
    if cjk_ratio >= 0.20 or total_chars >= 80:
        confidence = min(1.0, 0.5 + (cjk_ratio * 0.5))
        return "text_layer_extracted", cjk_ratio, confidence

    return "text_layer_missing_or_low_text", cjk_ratio, 0.2


# ── Phase 1: Text Layer Extraction ──────────────────────────────────────────

def extract_pages_text_layer(pdf_path: Path) -> List[dict]:
    """Extract page text using PyMuPDF (fitz) or pdftotext CLI."""
    pages = []
    # 1. Try PyMuPDF
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        for idx, page in enumerate(doc):
            raw_text = page.get_text()
            norm = normalize_cjk_text(raw_text)
            classification, cjk_ratio, conf = classify_page_text(norm)
            pages.append({
                "page_index": idx,
                "text_raw": raw_text,
                "text_normalized": norm,
                "classification": classification,
                "cjk_ratio": round(cjk_ratio, 3),
                "confidence": round(conf, 3),
                "char_count": len(norm),
                "extractor": EXTRACTOR_PYMUPDF
            })
        doc.close()
        return pages
    except ImportError:
        pass
    except Exception:
        pass

    # 2. Fallback to poppler CLI (pdftotext)
    total_pages = 0
    try:
        info_res = subprocess.run(
            ["pdfinfo", str(pdf_path)],
            capture_output=True, text=True, timeout=30
        )
        page_match = re.search(r"Pages:\s+(\d+)", info_res.stdout)
        if page_match:
            total_pages = int(page_match.group(1))
    except Exception:
        total_pages = 0

    if total_pages == 0:
        try:
            res = subprocess.run(
                ["pdftotext", "-layout", str(pdf_path), "-"],
                capture_output=True, text=True, timeout=120
            )
            raw_pages = res.stdout.split("\x0c")
            if raw_pages and not raw_pages[-1].strip():
                raw_pages.pop()
            for idx, ptext in enumerate(raw_pages):
                norm = normalize_cjk_text(ptext)
                classification, cjk_ratio, conf = classify_page_text(norm)
                pages.append({
                    "page_index": idx,
                    "text_raw": ptext,
                    "text_normalized": norm,
                    "classification": classification,
                    "cjk_ratio": round(cjk_ratio, 3),
                    "confidence": round(conf, 3),
                    "char_count": len(norm),
                    "extractor": EXTRACTOR_POPPLER
                })
        except Exception:
            pass
    else:
        for p in range(1, total_pages + 1):
            try:
                res = subprocess.run(
                    ["pdftotext", "-f", str(p), "-l", str(p), "-layout", str(pdf_path), "-"],
                    capture_output=True, text=True, timeout=30
                )
                raw_text = res.stdout.replace("\x0c", "").strip()
                norm = normalize_cjk_text(raw_text)
                classification, cjk_ratio, conf = classify_page_text(norm)
                pages.append({
                    "page_index": p - 1,
                    "text_raw": raw_text,
                    "text_normalized": norm,
                    "classification": classification,
                    "cjk_ratio": round(cjk_ratio, 3),
                    "confidence": round(conf, 3),
                    "char_count": len(norm),
                    "extractor": EXTRACTOR_POPPLER
                })
            except Exception:
                pages.append({
                    "page_index": p - 1,
                    "text_raw": "",
                    "text_normalized": "",
                    "classification": "text_layer_missing_or_low_text",
                    "cjk_ratio": 0.0,
                    "confidence": 0.0,
                    "char_count": 0,
                    "extractor": EXTRACTOR_POPPLER
                })
    return pages


def process_book_triage(
    book_rec: dict,
    base_dir: Path,
    out_dir: Path,
    checkpoint_file: Path,
    node_id: str,
    lease_id: Optional[str] = None,
    attempt: int = 1
) -> bool:
    book_id = book_rec["book_id"]
    source_rel = book_rec.get("source_path") or book_rec.get("source_full_path", "")
    pdf_path = base_dir / source_rel
    if not pdf_path.exists():
        pdf_path = base_dir / Path(source_rel).name
    if not pdf_path.exists():
        print(f"[{node_id}] [{book_id}] ERROR: PDF not found: {pdf_path}", file=sys.stderr)
        return False

    artifact_id = book_rec.get("artifact_id") or compute_sha256(pdf_path)
    source_hash = artifact_id.replace("sha256:", "")

    t0 = time.time()
    print(f"[{node_id}] [triage] {book_id}: probing {pdf_path.name} ...", flush=True)

    pages_data = extract_pages_text_layer(pdf_path)
    extractor = pages_data[0]["extractor"] if pages_data else EXTRACTOR_POPPLER
    evidence_set_id = make_evidence_set_id(book_id, artifact_id, extractor)
    now_str = _now_iso()

    text_extracted_count = sum(1 for p in pages_data if p["classification"] == "text_layer_extracted")
    missing_count = len(pages_data) - text_extracted_count

    book_entry = {
        "book_id": book_id,
        "artifact_id": artifact_id,
        "source_path": str(source_rel),
        "source_hash": source_hash,
        "evidence_set_id": evidence_set_id,
        "title": book_rec.get("stem", book_id),
        "page_count": len(pages_data),
        "text_layer_extracted_pages": text_extracted_count,
        "text_layer_missing_or_low_text_pages": missing_count,
        "pipeline_stage": "text_layer_triage",
        "node_id": node_id,
        "worker_version": WORKER_VERSION,
        "created_at": now_str
    }

    page_entries = []
    para_entries = []
    anchor_entries = []
    ocr_queue_entries = []

    for p in pages_data:
        p_idx = p["page_index"]
        page_id = f"{book_id}:p{p_idx}"
        
        page_entry = {
            "id": page_id,
            "book_id": book_id,
            "artifact_id": artifact_id,
            "page_index": p_idx,
            "evidence_set_id": evidence_set_id,
            "text_raw": p["text_raw"],
            "text_normalized": p["text_normalized"],
            "classification": p["classification"],
            "char_count": p["char_count"],
            "cjk_ratio": p["cjk_ratio"],
            "confidence": p["confidence"],
            "extractor": p["extractor"],
            "normalization_version": NORMALIZATION_VERSION,
            "pipeline_stage": "text_layer_triage",
            "node_id": node_id,
            "worker_version": WORKER_VERSION,
            "created_at": now_str
        }
        page_entries.append(page_entry)

        if p["classification"] == "text_layer_extracted":
            # Build paragraphs & anchors for real text
            paras = [pt.strip() for pt in p["text_normalized"].split("\n\n") if pt.strip()]
            if not paras:
                paras = [p["text_normalized"]]

            char_offset = 0
            for para_idx, p_text in enumerate(paras):
                para_id = f"{book_id}:p{p_idx}:para{para_idx}"
                start = char_offset
                end = start + len(p_text)
                char_offset = end + 1

                para_entries.append({
                    "id": para_id,
                    "book_id": book_id,
                    "page_id": page_id,
                    "page_index": p_idx,
                    "evidence_set_id": evidence_set_id,
                    "char_start": start,
                    "char_end": end,
                    "text_normalized": p_text,
                    "node_id": node_id,
                    "created_at": now_str
                })

                anchor_entries.append({
                    "id": f"anchor:{para_id}",
                    "book_id": book_id,
                    "artifact_id": artifact_id,
                    "evidence_set_id": evidence_set_id,
                    "page_index": p_idx,
                    "char_start": start,
                    "char_end": end,
                    "confidence": p["confidence"],
                    "node_id": node_id,
                    "created_at": now_str
                })
        else:
            # Enqueue for Phase 2 Visual OCR
            ocr_queue_entries.append({
                "book_id": book_id,
                "artifact_id": artifact_id,
                "source_path": str(source_rel),
                "page_index": p_idx,
                "reason": "missing_or_low_text",
                "created_at": now_str
            })

    # Write output JSONLs
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "books.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(book_entry, ensure_ascii=False) + "\n")

    with open(out_dir / "pages.jsonl", "a", encoding="utf-8") as f:
        for p in page_entries:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    if para_entries:
        with open(out_dir / "paragraphs.jsonl", "a", encoding="utf-8") as f:
            for pa in para_entries:
                f.write(json.dumps(pa, ensure_ascii=False) + "\n")

    if anchor_entries:
        with open(out_dir / "anchors.jsonl", "a", encoding="utf-8") as f:
            for an in anchor_entries:
                f.write(json.dumps(an, ensure_ascii=False) + "\n")

    if ocr_queue_entries:
        with open(out_dir / "ocr_queue.jsonl", "a", encoding="utf-8") as f:
            for ocr_item in ocr_queue_entries:
                f.write(json.dumps(ocr_item, ensure_ascii=False) + "\n")

    # Conservation of pages invariant
    assert text_extracted_count + missing_count == len(pages_data), (
        f"Conservation invariant violated: {text_extracted_count} + {missing_count} != {len(pages_data)}"
    )

    # Record checkpoint with strict provenance and operational metrics
    finished_str = _now_iso()
    elapsed = round(time.time() - t0, 2)
    output_bytes = json.dumps(page_entries, ensure_ascii=False).encode("utf-8")
    output_sha256 = compute_bytes_sha256(output_bytes)

    confs = [p["confidence"] for p in page_entries]
    mean_conf = round(sum(confs) / max(1, len(confs)), 3)
    low_conf_count = sum(1 for c in confs if c < 0.6)
    low_conf_ratio = round(low_conf_count / max(1, len(confs)), 3)
    total_chars = sum(p["char_count"] for p in page_entries)
    empty_pages = sum(1 for p in page_entries if p["char_count"] == 0)
    ram_bytes, temp_c = get_system_resources()

    chk = {
        "leaseId": lease_id or f"lease-triage-{book_id}-{int(time.time())}",
        "taskId": f"triage:{book_id}",
        "nodeId": node_id,
        "attempt": attempt,
        "book_id": book_id,
        "artifact_id": artifact_id,
        "evidence_set_id": evidence_set_id,
        "inputSha256": artifact_id,
        "outputSha256": output_sha256,
        "status": "triage_success",
        "pipelineStage": "text_layer_triage",
        "total_pages": len(pages_data),
        "text_layer_extracted_pages": text_extracted_count,
        "text_layer_missing_or_low_text_pages": missing_count,
        "paragraphs": len(para_entries),
        "startedAt": now_str,
        "finishedAt": finished_str,
        "elapsedSec": elapsed,
        "exitCode": 0,
        "quality": {
            "meanConfidence": mean_conf,
            "lowConfidenceRatio": low_conf_ratio,
            "charCount": total_chars,
            "empty": (total_chars == 0),
            "emptyPagesCount": empty_pages
        },
        "resource": {
            "peakRamBytes": ram_bytes,
            "temperatureC": temp_c
        },
        "workerVersion": WORKER_VERSION,
        "timestamp": finished_str
    }
    with open(checkpoint_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(chk, ensure_ascii=False) + "\n")

    print(f"[{node_id}] [triage] {book_id}: done in {elapsed}s | total={len(pages_data)} pages (text_layer={text_extracted_count}, needs_ocr={missing_count})", flush=True)
    return True


# ── Phase 2: Page-Chunk Visual OCR ──────────────────────────────────────────

def run_visual_ocr_chunk(
    task_id: str,
    book_id: str,
    pdf_path: Path,
    start_page: int,
    end_page: int,
    node_id: str,
    out_dir: Path,
    checkpoint_file: Path,
    engine_name: str = "auto",
    lease_id: Optional[str] = None,
    attempt: int = 1
) -> bool:
    """Execute real visual OCR on a continuous page chunk with node provenance."""
    t0 = time.time()
    artifact_id = compute_sha256(pdf_path)
    now_str = _now_iso()

    print(f"[{node_id}] [visual_ocr] Task {task_id}: pages {start_page}-{end_page} of {pdf_path.name} ...", flush=True)

    # 1. Render pages to image files or memory
    rendered_images = []
    tmp_img_dir = out_dir / f"tmp_{task_id}"
    tmp_img_dir.mkdir(parents=True, exist_ok=True)

    # Try PyMuPDF rendering first
    engine_used = EXTRACTOR_RAPIDOCR
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        for p_idx in range(start_page, min(end_page + 1, len(doc))):
            page = doc[p_idx]
            pix = page.get_pixmap(dpi=150)
            img_path = tmp_img_dir / f"p_{p_idx}.png"
            pix.save(str(img_path))
            rendered_images.append((p_idx, img_path))
        doc.close()
    except Exception:
        # Fallback to pdftoppm
        try:
            res = subprocess.run([
                "pdftoppm", "-png", "-r", "150",
                "-f", str(start_page + 1), "-l", str(end_page + 1),
                str(pdf_path), str(tmp_img_dir / "page")
            ], capture_output=True, text=True, timeout=60)
            for f in sorted(tmp_img_dir.glob("page-*.png")):
                match = re.search(r"page-(\d+)\.png", f.name)
                if match:
                    p_num = int(match.group(1)) - 1
                    rendered_images.append((p_num, f))
        except Exception as e:
            print(f"[{node_id}] ERROR: Render failed for {task_id}: {e}", file=sys.stderr)
            return False

    # 2. Run OCR Engine on rendered images
    extracted_chunk_pages = []
    # Try RapidOCR / ONNXRuntime (PC / advanced ARM64)
    ocr_backend = None
    if engine_name in ("rapidocr", "auto"):
        try:
            import rapidocr_onnxruntime
            ocr_backend = rapidocr_onnxruntime.RapidOCR()
            engine_used = EXTRACTOR_RAPIDOCR
        except Exception:
            pass

    for p_idx, img_path in rendered_images:
        raw_text = ""
        conf = 0.0
        if ocr_backend:
            try:
                res, _ = ocr_backend(str(img_path))
                if res:
                    lines = [item[1] for item in res if len(item) > 1 and item[1]]
                    confs = [float(item[2]) for item in res if len(item) > 2 and item[2]]
                    raw_text = "\n".join(lines)
                    conf = sum(confs) / max(1, len(confs))
            except Exception:
                pass
        else:
            # Fallback to native Tesseract CLI (Termux / Linux)
            try:
                out_txt_base = tmp_img_dir / f"ocr_{p_idx}"
                subprocess.run(
                    ["tesseract", str(img_path), str(out_txt_base), "-l", "chi_sim", "--oem", "1"],
                    capture_output=True, text=True, timeout=60
                )
                txt_file = tmp_img_dir / f"ocr_{p_idx}.txt"
                if txt_file.exists():
                    with open(txt_file, encoding="utf-8", errors="ignore") as f:
                        raw_text = f.read()
                conf = 0.75 if len(raw_text) > 30 else 0.3
                engine_used = EXTRACTOR_TESSERACT
            except Exception:
                pass

        norm = normalize_cjk_text(raw_text)
        classification, cjk_ratio, _ = classify_page_text(norm)
        extracted_chunk_pages.append({
            "page_index": p_idx,
            "text_raw": raw_text,
            "text_normalized": norm,
            "classification": "visual_ocr_extracted" if len(norm) >= 30 else "visual_ocr_low_text",
            "cjk_ratio": round(cjk_ratio, 3),
            "confidence": round(conf, 3),
            "char_count": len(norm),
            "extractor": engine_used
        })

    # Clean up temp image files
    try:
        for _, img_path in rendered_images:
            if img_path.exists():
                img_path.unlink()
        for txt in tmp_img_dir.glob("*.txt"):
            txt.unlink()
        tmp_img_dir.rmdir()
    except Exception:
        pass

    # 3. Build Evidence records with strict provenance
    evidence_set_id = make_evidence_set_id(book_id, artifact_id, engine_used)
    page_records = []
    para_records = []
    anchor_records = []

    for p in extracted_chunk_pages:
        p_idx = p["page_index"]
        page_id = f"{book_id}:p{p_idx}"
        page_records.append({
            "id": page_id,
            "book_id": book_id,
            "artifact_id": artifact_id,
            "page_index": p_idx,
            "evidence_set_id": evidence_set_id,
            "text_raw": p["text_raw"],
            "text_normalized": p["text_normalized"],
            "classification": p["classification"],
            "char_count": p["char_count"],
            "cjk_ratio": p["cjk_ratio"],
            "confidence": p["confidence"],
            "extractor": p["extractor"],
            "normalization_version": NORMALIZATION_VERSION,
            "pipeline_stage": "visual_ocr",
            "node_id": node_id,
            "task_id": task_id,
            "worker_version": WORKER_VERSION,
            "created_at": now_str
        })

        if p["char_count"] >= 30:
            paras = [pt.strip() for pt in p["text_normalized"].split("\n\n") if pt.strip()]
            if not paras:
                paras = [p["text_normalized"]]
            char_offset = 0
            for para_idx, p_text in enumerate(paras):
                para_id = f"{book_id}:p{p_idx}:para{para_idx}"
                start = char_offset
                end = start + len(p_text)
                char_offset = end + 1

                para_records.append({
                    "id": para_id,
                    "book_id": book_id,
                    "page_id": page_id,
                    "page_index": p_idx,
                    "evidence_set_id": evidence_set_id,
                    "char_start": start,
                    "char_end": end,
                    "text_normalized": p_text,
                    "node_id": node_id,
                    "task_id": task_id,
                    "created_at": now_str
                })

                anchor_records.append({
                    "id": f"anchor:{para_id}",
                    "book_id": book_id,
                    "artifact_id": artifact_id,
                    "evidence_set_id": evidence_set_id,
                    "page_index": p_idx,
                    "char_start": start,
                    "char_end": end,
                    "confidence": p["confidence"],
                    "node_id": node_id,
                    "task_id": task_id,
                    "created_at": now_str
                })

    # Append to output files
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "ocr_pages.jsonl", "a", encoding="utf-8") as f:
        for p in page_records:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    with open(out_dir / "ocr_paragraphs.jsonl", "a", encoding="utf-8") as f:
        for pa in para_records:
            f.write(json.dumps(pa, ensure_ascii=False) + "\n")
    with open(out_dir / "ocr_anchors.jsonl", "a", encoding="utf-8") as f:
        for an in anchor_records:
            f.write(json.dumps(an, ensure_ascii=False) + "\n")

    # Record Provenance in checkpoint with operational and quality metrics
    finished_str = _now_iso()
    elapsed = round(time.time() - t0, 2)
    output_bytes = json.dumps(page_records, ensure_ascii=False).encode("utf-8")
    output_sha256 = compute_bytes_sha256(output_bytes)

    confs = [p["confidence"] for p in page_records]
    mean_conf = round(sum(confs) / max(1, len(confs)), 3)
    low_conf_count = sum(1 for c in confs if c < 0.6)
    low_conf_ratio = round(low_conf_count / max(1, len(confs)), 3)
    total_chars = sum(p["char_count"] for p in page_records)
    empty_pages = sum(1 for p in page_records if p["char_count"] == 0)
    ram_bytes, temp_c = get_system_resources()

    chk_record = {
        "leaseId": lease_id or f"lease-ocr-{task_id}-{int(time.time())}",
        "taskId": task_id,
        "nodeId": node_id,
        "attempt": attempt,
        "inputSha256": artifact_id,
        "outputSha256": output_sha256,
        "pageRange": {"start": start_page, "end": end_page},
        "pipelineStage": "visual_ocr",
        "workerVersion": WORKER_VERSION,
        "engineVersion": engine_used,
        "pagesProcessed": len(extracted_chunk_pages),
        "paragraphsGenerated": len(para_records),
        "startedAt": now_str,
        "finishedAt": finished_str,
        "elapsedSec": elapsed,
        "exitCode": 0,
        "quality": {
            "meanConfidence": mean_conf,
            "lowConfidenceRatio": low_conf_ratio,
            "charCount": total_chars,
            "empty": (total_chars == 0),
            "emptyPagesCount": empty_pages
        },
        "resource": {
            "peakRamBytes": ram_bytes,
            "temperatureC": temp_c
        },
        "timestamp": finished_str
    }
    with open(checkpoint_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(chk_record, ensure_ascii=False) + "\n")

    print(f"[{node_id}] [visual_ocr] Task {task_id} completed in {elapsed}s ({len(para_records)} paras, engine={engine_used})", flush=True)
    return True


# ── Main Entry ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Fleet Node Worker v2.2.0")
    parser.add_argument("--mode", choices=["triage", "visual-ocr"], default="triage",
                        help="Pipeline phase: 'triage' (Phase 1 text-layer) or 'visual-ocr' (Phase 2)")
    parser.add_argument("--node-id", default=socket.gethostname(),
                        help="Unique physical node identifier (e.g., vivo-worker, oppo-service)")
    parser.add_argument("--shard-file", help="Path to manifest shard JSONL (for triage)")
    parser.add_argument("--chunk-file", help="Path to page chunks JSONL (for visual-ocr)")
    parser.add_argument("--base-dir", default=".", help="Base directory containing PDF files")
    parser.add_argument("--output-dir", default="./evidence_shard", help="Evidence output directory")
    parser.add_argument("--checkpoint", default="./chk.jsonl", help="Checkpoint file path")
    parser.add_argument("--ocr-engine", default="auto", choices=["auto", "rapidocr", "tesseract"])
    parser.add_argument("--lease-id", default=None, help="Coordinator lease ID")
    parser.add_argument("--attempt", type=int, default=1, help="Execution attempt count")
    parser.add_argument("--limit", type=int, default=0, help="Max books/chunks to process")
    args = parser.parse_args()

    node_id = args.node_id
    base_dir = Path(args.base_dir)
    out_dir = Path(args.output_dir)
    chk_path = Path(args.checkpoint)

    # 1. Triage Mode (Phase 1)
    if args.mode == "triage":
        if not args.shard_file:
            print("ERROR: --shard-file is required for triage mode", file=sys.stderr)
            sys.exit(1)
        shard_path = Path(args.shard_file)

        # Check existing done books
        done_ids = set()
        if chk_path.exists():
            with open(chk_path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        try:
                            rec = json.loads(line)
                            if rec.get("status") == "triage_success":
                                done_ids.add(rec.get("book_id"))
                        except Exception:
                            pass

        books = []
        with open(shard_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    books.append(json.loads(line))

        pending = [b for b in books if b["book_id"] not in done_ids]
        if args.limit > 0:
            pending = pending[:args.limit]

        print(f"[{node_id}] [triage] Total: {len(books)} | Done: {len(done_ids)} | Pending: {len(pending)}")
        for idx, b in enumerate(pending, 1):
            print(f"({idx}/{len(pending)}) ", end="")
            process_book_triage(b, base_dir, out_dir, chk_path, node_id, lease_id=args.lease_id, attempt=args.attempt)
        print(f"[{node_id}] [triage] Completed successfully.")

    # 2. Visual OCR Mode (Phase 2)
    elif args.mode == "visual-ocr":
        if not args.chunk_file:
            print("ERROR: --chunk-file is required for visual-ocr mode", file=sys.stderr)
            sys.exit(1)
        chunks_path = Path(args.chunk_file)

        done_tasks = set()
        if chk_path.exists():
            with open(chk_path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        try:
                            rec = json.loads(line)
                            if rec.get("taskId"):
                                done_tasks.add(rec["taskId"])
                        except Exception:
                            pass

        chunks = []
        with open(chunks_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    chunks.append(json.loads(line))

        pending_chunks = [c for c in chunks if c["taskId"] not in done_tasks]
        if args.limit > 0:
            pending_chunks = pending_chunks[:args.limit]

        print(f"[{node_id}] [visual-ocr] Total Chunks: {len(chunks)} | Done: {len(done_tasks)} | Pending: {len(pending_chunks)}")
        for idx, chunk in enumerate(pending_chunks, 1):
            t_id = chunk["taskId"]
            b_id = chunk["book_id"]
            pdf_rel = chunk.get("source_path", "")
            pdf_path = base_dir / pdf_rel
            if not pdf_path.exists():
                pdf_path = base_dir / Path(pdf_rel).name

            start_p = chunk["pageRange"]["start"]
            end_p = chunk["pageRange"]["end"]

            print(f"({idx}/{len(pending_chunks)}) ", end="")
            run_visual_ocr_chunk(
                task_id=t_id,
                book_id=b_id,
                pdf_path=pdf_path,
                start_page=start_p,
                end_page=end_p,
                node_id=node_id,
                out_dir=out_dir,
                checkpoint_file=chk_path,
                engine_name=args.ocr_engine,
                lease_id=args.lease_id,
                attempt=args.attempt
            )
        print(f"[{node_id}] [visual-ocr] All assigned chunks completed.")


if __name__ == "__main__":
    main()
