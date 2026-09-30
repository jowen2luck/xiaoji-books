#!/usr/bin/env python3
"""
Batch-ingest OCR pages/paragraphs from data/.ocr_reprocess/ into catalog.db.

Reads per-book files:
  data/.ocr_reprocess/{book_id}_pages.jsonl      (page-level)
  data/.ocr_reprocess/{book_id}_paragraphs.jsonl (paragraph-level)

and inserts into catalog.db (books, pages, paragraphs, evidence_sets, paragraphs_fts).

Handles watermark filtering, FTS index rebuild, and idempotent re-runs.
"""

import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OCR_DIR = PROJECT_ROOT / "data" / ".ocr_reprocess"
DB_PATH = PROJECT_ROOT / "data" / "catalog" / "catalog.db"
MANIFEST_PATH = PROJECT_ROOT / "data" / "manifest.jsonl"

TITLE_HINTS = [
    (r'书名\s*[:=]\s*([^\r\n]+)', 1),
    (r'《([^》\r\n]{2,30})》', 1),
]

WATERMARK_PATTERNS = ['pdffactory', 'fineprint', 'pdf factory', '试用版', 'trial version']

CAT_RULES = [
    (r'苏联历史档案选编', '苏联档案'),
    (r'\bmarx\b', '马恩列斯'),
    (r'\blenin\b', '马恩列斯'),
    (r'\bstalin\b', '苏联档案'),
    (r'\bkautsky\b', '国际共运'),
    (r'\bluxemburg\b', '国际共运'),
    (r'\btrotsky\b', '托洛茨基研究'),
    (r'bukharin', '苏联档案'),
    (r'hegel', '哲学经典'),
    (r'hobsbawm', '史学理论'),
    (r'国际歌', '国际歌研究'),
    (r'internationale', '国际歌研究'),
    (r'巴黎公社', '巴黎公社研究'),
    (r'pottier', '国际歌研究'),
    (r'工人运动', '工人运动'),
    (r'共产党宣言', '马恩列斯'),
    (r'资本论', '马恩列斯'),
    (r'债权人', '债权人会议材料'),
    (r'\b\d{8}[a-z]?\b', '剪报史料'),
    (r'联共|苏共', '苏联档案'),
    (r'东北问题', '史料杂钞'),
    (r'剪报', '剪报史料'),
    (r'mao|mao zedong|毛泽东', '毛泽东研究'),
    (r'周恩来', '周恩来研究'),
]


def slugify(book_id, manifest_map):
    m = manifest_map.get(book_id, {})
    src = m.get('source_path', '') or m.get('source_full_path', '')
    title = m.get('title', '')
    return src, title


def infer_title(book_id, manifest_map, paras_text):
    """Try to extract a human-readable title."""
    _, mtitle = slugify(book_id, manifest_map)
    if mtitle and not mtitle.startswith('book-') and not re.match(r'^\d{6,}', mtitle):
        return mtitle

    # From paragraph text early pages
    early = paras_text[:4000] if paras_text else ''
    for pat, grp in TITLE_HINTS:
        mt = re.search(pat, early)
        if mt:
            t = mt.group(grp).strip().strip('《》')
            if 2 <= len(t) <= 60:
                return t

    # fallback: use manifest source path
    src, _ = slugify(book_id, manifest_map)
    base = Path(src).stem.replace('-', ' ').replace('_', ' ') if src else ''
    base = base.strip()
    if base:
        return base
    return book_id


def infer_category(book_id, title, manifest_map):
    combined = f"{book_id} {title} {manifest_map.get(book_id, {}).get('source_path', '')}".lower()
    for pat, cat in CAT_RULES:
        if re.search(pat, combined, re.I):
            return cat
    return '综合史料'


def is_watermark(text):
    if not text or not text.strip():
        return True
    low = text.lower()
    return any(p in low for p in WATERMARK_PATTERNS)


def load_manifest_map():
    m = {}
    if not MANIFEST_PATH.exists():
        return m
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                m[r.get('book_id', '')] = r
            except json.JSONDecodeError:
                continue
    return m


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Ingest .ocr_reprocess/*.jsonl into catalog.db")
    parser.add_argument("--force", action="store_true", help="Re-ingest even if already in catalog")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=OFF")

    # Existing book ids
    existing = {r[0] for r in db.execute("SELECT book_id FROM books").fetchall()}

    # Discover books with _pages.jsonl or _paragraphs.jsonl in .ocr_reprocess
    book_ids = set()
    for f in OCR_DIR.glob("*_pages.jsonl"):
        book_ids.add(f.name.replace("_pages.jsonl", ""))
    for f in OCR_DIR.glob("*_paragraphs.jsonl"):
        if f.name.replace("_paragraphs.jsonl", "") not in book_ids:
            book_ids.add(f.name.replace("_paragraphs.jsonl", ""))

    manifest = load_manifest_map()
    book_ids = sorted(book_ids)
    if args.limit:
        book_ids = book_ids[: args.limit]

    print(f"Found {len(book_ids)} candidate books in {OCR_DIR}")

    stats = {"total": len(book_ids), "ingested": 0, "skipped_watermark_only": 0,
             "skipped_already": 0, "errors": 0, "total_paragraphs": 0}
    t0 = time.time()

    for bid in book_ids:
        if bid in existing and not args.force:
            stats["skipped_already"] += 1
            continue

        try:
            pages_file = OCR_DIR / f"{bid}_pages.jsonl"
            paras_file = OCR_DIR / f"{bid}_paragraphs.jsonl"

            # Read paragraphs first (preferred source)
            paras = []
            if paras_file.exists():
                with open(paras_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line=line.strip()
                        if not line:
                            continue
                        try:
                            paras.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue

            # If no paragraphs, synthesize from pages
            pages = []
            if not paras and pages_file.exists():
                with open(pages_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line=line.strip()
                        if not line:
                            continue
                        try:
                            pages.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
                # Simple slicing per page → 1-para-per-block
                for pg in pages:
                    text = pg.get("text_raw", "") or pg.get("text_normalized", "")
                    if not text.strip():
                        continue
                    for block in text.split("\n\n"):
                        block = block.strip()
                        if block and len(block) >= 2:
                            paras.append({
                                "id": f"{bid}:p{pg.get('page_index',0)}:{len(paras)}",
                                "page_id": f"{bid}:p{pg.get('page_index',0)}",
                                "page_index": pg.get("page_index", 0),
                                "printed_page": pg.get("printed_page", ""),
                                "text_normalized": block,
                                "text_raw": block,
                            })

            # Filter watermark paragraphs
            paras = [p for p in paras if not is_watermark(p.get("text_normalized", "") or p.get("text_raw", ""))]

            if not paras:
                stats["skipped_watermark_only"] += 1
                print(f"  [SKIP] {bid}: watermark-only")
                continue

            # Title + category
            all_text = "\n".join(p.get("text_normalized", "") or "" for p in paras[:20])
            title = infer_title(bid, manifest, all_text)
            category = infer_category(bid, title, manifest)

            meta = manifest.get(bid, {})
            page_count = meta.get("page_count") or len(pages) or max(
                (p.get("page_index", 0) for p in paras), default=0
            ) + 1
            if page_count < 1:
                page_count = 1

            artifact_id = meta.get("artifact_id") or f"art://{bid}"
            source_path = meta.get("source_path") or meta.get("source_full_path") or meta.get("pdf_path") or ""
            # 确保入库的是绝对路径：如果是相对路径，自动拼 data/_kage/www.marxists.org/
            if source_path and not os.path.isabs(source_path) and not source_path.startswith('\\\\'):
                candidate = str(PROJECT_ROOT / "data" / "_kage" / "www.marxists.org" / source_path)
                if os.path.isfile(candidate):
                    source_path = str(Path(candidate).resolve())

            source_hash = ""
            if artifact_id.startswith("sha256:"):
                source_hash = artifact_id[7:]

            es_id = f"mobile-ingest-{bid}"

            if not args.dry_run:
                # Clear old entries if force
                if args.force:
                    db.execute("DELETE FROM paragraphs_fts WHERE book_id=?", (bid,))
                    db.execute("DELETE FROM paragraphs WHERE book_id=?", (bid,))
                    db.execute("DELETE FROM pages WHERE book_id=?", (bid,))
                    db.execute("DELETE FROM evidence_sets WHERE book_id=?", (bid,))
                    db.execute("DELETE FROM books WHERE book_id=?", (bid,))

                # Insert book
                db.execute("""
                    INSERT OR REPLACE INTO books
                    (book_id, artifact_id, source_path, title, authors, language,
                     page_count, status, ingested_at, evidence_set_id, source_hash,
                     primary_category, tags)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    bid, artifact_id, source_path,
                    title, meta.get("authors", "史料编纂组") or "史料编纂组",
                    "zh", page_count, "processed", time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    es_id, source_hash, category, json.dumps([category], ensure_ascii=False)
                ))

                # Insert pages
                for pg in (pages or []):
                    pid = pg.get("id") or f"{bid}:p{pg.get('page_index',0)}"
                    pidx = pg.get("page_index", 0)
                    db.execute("""
                        INSERT OR REPLACE INTO pages
                        (id, book_id, artifact_id, evidence_set_id, page_index, printed_page,
                         text_raw, text_normalized, normalization_version, confidence, char_count)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """, (
                        pid, bid, artifact_id, es_id, pidx,
                        pg.get("printed_page", str(pidx + 1)),
                        pg.get("text_raw", ""), pg.get("text_normalized", ""),
                        pg.get("normalization_version", "norm_v1"),
                        pg.get("confidence", 0.9),
                        len(pg.get("text_normalized", "")),
                    ))

                # Insert FTS-safe: clear old, insert new
                db.execute("DELETE FROM paragraphs_fts WHERE book_id=?", (bid,))
                for i, p in enumerate(paras):
                    text = (p.get("text_normalized", "") or p.get("text_raw", "")).strip()
                    if not text:
                        continue
                    pid = p.get("id") or f"{bid}:p{p.get('page_index',0)}:{i}"
                    pidx = p.get("page_index", 0)
                    db.execute("""
                        INSERT OR REPLACE INTO paragraphs
                        (id, book_id, artifact_id, evidence_set_id, page_id, page_index,
                         printed_page, para_index, text_normalized, text_raw,
                         normalization_version, char_start, char_end, confidence)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (
                        pid, bid, artifact_id, es_id,
                        p.get("page_id") or f"{bid}:p{pidx}",
                        pidx, p.get("printed_page", str(pidx + 1)),
                        p.get("para_index", i),
                        text, p.get("text_raw", text),
                        p.get("normalization_version", "norm_v1"),
                        p.get("char_start", 0), p.get("char_end", len(text)),
                        p.get("confidence", 0.9) if "confidence" in p else 0.9,
                    ))
                    db.execute("""
                        INSERT INTO paragraphs_fts (paragraph_id, book_id, page_index, text_normalized)
                        VALUES (?,?,?,?)
                    """, (pid, bid, pidx, text))

                # Insert evidence set
                db.execute("""
                    INSERT OR REPLACE INTO evidence_sets
                    (evidence_set_id, book_id, artifact_id, extractor_sig, normalization_version,
                     page_count, paragraph_count, loaded_at)
                    VALUES (?,?,?,?,?,?,?,?)
                """, (
                    es_id, bid, artifact_id, "mobile_ingest@1.0", "norm_v1",
                    page_count, len(paras), time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                ))

                db.commit()

            stats["ingested"] += 1
            stats["total_paragraphs"] += len(paras)
            print(f"  [OK] {bid}: {title} — {len(paras)} paras")

        except Exception as e:
            stats["errors"] += 1
            print(f"  [ERR] {bid}: {str(e)[:200]}")
            try:
                db.rollback()
            except:
                pass

    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"Ingestion complete:")
    print(f"  Ingested: {stats['ingested']}")
    print(f"  Skipped (watermark only): {stats['skipped_watermark_only']}")
    print(f"  Skipped (already in catalog): {stats['skipped_already']}")
    print(f"  Errors: {stats['errors']}")
    print(f"  Total paragraphs: {stats['total_paragraphs']}")
    print(f"  Time: {elapsed:.1f}s")

    # Verify count
    vc = db.execute("SELECT COUNT(*) FROM books WHERE book_id IN ({})".format(
        ",".join(f"'{b}'" for b in book_ids)
    )).fetchone()[0]
    print(f"  Verified books in catalog: {vc}")

    db.close()


if __name__ == "__main__":
    main()
