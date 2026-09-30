#!/usr/bin/env python3
"""
block_structure.py — Layer A/B/C: Geometry Classification, Reading Order, Paragraph Assembly.

Reads: data/evidence/shard*/blocks.jsonl  (Ground Truth, immutable)
Writes per book:
  navigation/<book_id>/page_structure.jsonl   — Layer A output
  navigation/<book_id>/paragraphs_v2.jsonl     — Layer C output
  navigation/<book_id>/ocr_flags.jsonl          — Layer D output (flags only, no corrections)
  navigation/<book_id>/doc_meta.json            — Layer E output

Design principles:
  - Ground Truth (blocks.jsonl) is never modified.
  - All inferred structure goes into navigation/ files.
  - Each navigation record has input_refs pointing back to block ids.
"""

import argparse
import json
import os
import re
import statistics
import sys
from collections import defaultdict, Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from layout_analyzer import LayoutAnalyzer

# ─── Config ───────────────────────────────────────────────────────────────

SHARD_PATHS = [
    "data/evidence/shard1/blocks.jsonl",
    "data/evidence/shard2/blocks.jsonl",
    "data/evidence/shard3/blocks.jsonl",
    "data/evidence/shard4/blocks.jsonl",
]

OUTPUT_ROOT = "data/evidence/navigation"

# Tuning parameters
RUN_HEADER_MIN_PAGES = 3         # min pages for a text to be considered running header
RUN_HEADER_Y_TOLERANCE = 40      # y-position tolerance for matching (headers vary ±20px)
RUN_HEADER_X_TOLERANCE = 80      # x-position tolerance for matching
RUN_HEADER_MIN_TEXT_LEN = 2      # min length of header text
RUN_HEADER_MAX_TEXT_LEN = 45     # max length of header text

COLUMN_MIN_GAP = 70              # min x-gap between columns (px)
PARA_MAX_GAP_Y = 15              # max y-gap within same-line blocks (px)
PARA_BREAK_GAP_Y = 28            # y-gap above this triggers new paragraph
SECTION_TITLE_MIN_HEIGHT_RATIO = 1.3  # bbox height ratio vs median
SECTION_TITLE_MAX_Y_RATIO = 0.25     # y-position as fraction of page height

PAGE_NUMBER_PATTERN = re.compile(r'^[\d\-–—·.\s]{1,8}$')

# Common OCR confusion dictionary (for flagging, not correcting)
OCR_CONFUSIONS = {
    "榕琅": "喀",
    "余集": "全集",
    "類": "颊",
    "象含": "像含",
    "害怕": "伯害",  # partial match - will check context
    "精作": "奋斗",
    "车轮滚": "车轮滚滚",
}

# ─── Helpers ──────────────────────────────────────────────────────────────

def block_center_x(b):
    return (b["box"][0][0] + b["box"][2][0]) / 2

def block_top_y(b):
    return b["box"][0][1]

def block_width(b):
    return b["box"][2][0] - b["box"][0][0]

def block_height(b):
    return b["box"][2][1] - b["box"][0][1]

def load_blocks_for_book(book_id, shard_paths):
    """Load all blocks for a specific book from all shards."""
    blocks = []
    for path in shard_paths:
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    b = json.loads(line)
                    if b["book_id"] == book_id:
                        blocks.append(b)
    return blocks


def load_all_blocks(shard_paths):
    """Load all blocks, return {book_id: [blocks]}."""
    book_blocks = defaultdict(list)
    for path in shard_paths:
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    b = json.loads(line)
                    book_blocks[b["book_id"]].append(b)
    return book_blocks


def group_by_page(blocks):
    """Group blocks by page_index. Returns {page_index: [blocks]}."""
    pages = defaultdict(list)
    for b in blocks:
        pages[b["page_index"]].append(b)
    return pages


def detect_page_height(page_blocks):
    """Estimate page height from block positions."""
    if not page_blocks:
        return 1500  # default
    return max(b["box"][2][1] for b in page_blocks) + 50


# ─── Layer A: Geometry Classification ────────────────────────────────────

def detect_running_headers(pages):
    """
    Find text that repeats at the same position across multiple pages.
    Returns set of block_ids that are running headers.
    """
    # Build position -> {(text, block_id)} map
    pos_map = defaultdict(lambda: defaultdict(set))
    
    for pi, blocks in pages.items():
        for b in blocks:
            txt = b["text_raw"].strip()
            if not txt or len(txt) < RUN_HEADER_MIN_TEXT_LEN or len(txt) > RUN_HEADER_MAX_TEXT_LEN:
                continue
            # Skip pure numbers
            if txt.replace("-", "").replace(" ", "").replace("—", "").replace("·", "").replace(".", "").isdigit():
                continue
            # Bucket the position (use floor division so nearby coords map to same bucket)
            y_b = int(block_top_y(b) / RUN_HEADER_Y_TOLERANCE) * RUN_HEADER_Y_TOLERANCE
            x_b = int(block_center_x(b) / RUN_HEADER_X_TOLERANCE) * RUN_HEADER_X_TOLERANCE
            pos_map[(y_b, x_b)][txt].add(b["id"])
    
    # Find positions where same text appears on >= RUN_HEADER_MIN_PAGES pages
    header_block_ids = set()
    header_texts = {}
    
    for (y_b, x_b), text_ids_map in pos_map.items():
        for txt, block_ids in text_ids_map.items():
            if len(block_ids) >= RUN_HEADER_MIN_PAGES:
                header_block_ids.update(block_ids)
                header_texts[(y_b, x_b)] = txt
    
    return header_block_ids, header_texts


def classify_blocks(page_blocks, page_height, median_block_height, header_block_ids):
    """
    Classify each block on a page.
    Returns list of (block, role) tuples.
    """
    classified = []
    
    for b in page_blocks:
        bid = b["id"]
        txt = b["text_raw"].strip()
        y = block_top_y(b)
        h = block_height(b)
        x = block_center_x(b)
        
        role = "body"  # default
        
        # 1. Running header (cross-page repeated text)
        if bid in header_block_ids:
            role = "running_header"
        
        # 2. Page number: isolated number at edge
        elif PAGE_NUMBER_PATTERN.match(txt) and len(txt) <= 8:
            if x < 200 or x > 800:
                role = "page_number"
        
        # 3. Section title: taller text, upper part of page, short
        elif (h > median_block_height * SECTION_TITLE_MIN_HEIGHT_RATIO and 
              len(txt) <= 35 and 
              y < page_height * SECTION_TITLE_MAX_Y_RATIO):
            role = "section_title"
        
        # 4. Very small/unicode artifacts
        elif len(txt) == 1 and txt not in "。！？…—·":
            if not txt.isalnum():
                role = "artifact"
        
        classified.append((b, role))
    
    return classified


# ─── Layer B: Reading Order Restoration ───────────────────────────────────

def detect_columns(blocks):
    """
    Detect columns from block x-position histogram.
    Returns list of (x_center, [block_ids]) sorted left to right.
    """
    if not blocks:
        return []
    
    # Collect x-positions of body blocks
    xs = [block_center_x(b) for b in blocks if block_width(b) > 50]  # skip tiny artifacts
    if not xs:
        return []
    
    # Histogram with adaptive bin size
    sorted_xs = sorted(xs)
    
    # Find gaps between adjacent sorted positions
    columns = []
    current_col = [sorted_xs[0]]
    
    for i in range(1, len(sorted_xs)):
        if sorted_xs[i] - sorted_xs[i-1] > COLUMN_MIN_GAP:
            columns.append(statistics.median(current_col))
            current_col = [sorted_xs[i]]
        else:
            current_col.append(sorted_xs[i])
    columns.append(statistics.median(current_col))
    
    return columns


def sort_blocks_column_order(body_blocks, columns):
    """
    Sort body blocks: columns left to right, within each column sort by y.
    For archival/TOC pages (blocks at different y-levels per column), 
    sort each column independently by y-top.
    """
    if not body_blocks:
        return []
    
    # If only one column, simple y-sort
    if len(columns) <= 1:
        return sorted(body_blocks, key=lambda b: block_top_y(b))
    
    # Assign each block to nearest column
    col_blocks = defaultdict(list)
    for b in body_blocks:
        x = block_center_x(b)
        nearest_col = min(columns, key=lambda c: abs(c - x))
        col_blocks[nearest_col].append(b)
    
    # Sort columns left to right
    result = []
    for col_x in sorted(columns):
        # Sort blocks within this column by y
        col_sorted = sorted(col_blocks[col_x], key=lambda b: block_top_y(b))
        result.extend(col_sorted)
    
    return result


# ─── Layer C: Paragraph Assembly ─────────────────────────────────────────

def assemble_paragraphs(sorted_blocks, page_height):
    """
    Merge adjacent body blocks into paragraph structures.
    
    Strategy:
    - Blocks on the SAME line (y within PARA_MAX_GAP_Y) = same paragraph
    - Blocks with small y-gap (<PARA_BREAK_GAP_Y) = continuation of paragraph
    - Blocks with large y-gap (>=PARA_BREAK_GAP_Y) = new paragraph
    - Starts with "No." pattern = new paragraph (archival entry)
    - Archival pages (multi-column, No.xxxx entries): column-aware assembly
    """
    if not sorted_blocks:
        return []
    
    # Detect archival pages (>= 2 No.xxxx blocks indicates archival)
    no_count = sum(1 for b in sorted_blocks 
                   if re.match(r'^No[\.\s]?\d+', b["text_raw"].strip()))
    
    if no_count >= 2:
        return _assemble_paragraphs_archival(sorted_blocks, page_height)
    else:
        return _assemble_paragraphs_prose(sorted_blocks, page_height)


def _assemble_paragraphs_prose(sorted_blocks, page_height):
    """Paragraph assembly for prose/non-archival pages."""
    sorted_blocks = sorted(sorted_blocks, key=lambda b: (block_top_y(b), block_center_x(b)))
    
    paragraphs = []
    current_group = [sorted_blocks[0]]
    
    for i in range(1, len(sorted_blocks)):
        prev = sorted_blocks[i - 1]
        curr = sorted_blocks[i]
        
        prev_y = block_top_y(prev)
        curr_y = block_top_y(curr)
        prev_h = block_height(prev)
        prev_x = block_center_x(prev)
        curr_x = block_center_x(curr)
        
        y_between = curr_y - (prev_y + prev_h)
        same_line = abs(curr_y - prev_y) <= PARA_MAX_GAP_Y
        x_gap = abs(curr_x - prev_x)
        
        force_new = False
        curr_text = curr["text_raw"].strip()
        
        # Starts with archival entry marker (No.xxxx)
        if curr_text and re.match(r'^No[\.\s]?\d+', curr_text):
            force_new = True
        
        # Block starts with Chinese numeral + chapter marker
        if curr_text and re.match(r'^第[一二三四五六七八九十百]+', curr_text):
            force_new = True
        
        # Different columns on same row → different paragraphs
        if same_line and x_gap > COLUMN_MIN_GAP * 1.5:
            force_new = True
        
        # Large y-gap (>= threshold) → paragraph break
        if y_between >= PARA_BREAK_GAP_Y:
            force_new = True
        
        if force_new:
            if current_group:
                paragraphs.append(make_para_record(current_group))
            current_group = [curr]
        else:
            current_group.append(curr)
    
    if current_group:
        paragraphs.append(make_para_record(current_group))
    
    return paragraphs


def _assemble_paragraphs_archival(sorted_blocks, page_height):
    """
    Column-aware paragraph assembly for archival pages.
    
    Strategy:
    1. Group blocks into columns by x-position
    2. Find "No.xxxx" anchors in the leftmost column
    3. Each anchor + nearby right-column blocks (same y-band) = one entry paragraph
    4. Blocks above the first anchor (section titles) become separate paragraphs
    """
    # Detect columns for this page
    body_for_cols = [b for b in sorted_blocks if block_width(b) > 50]
    columns = detect_columns(body_for_cols) if body_for_cols else []
    
    if len(columns) < 2:
        # Fallback to prose assembly if columns not detected
        return _assemble_paragraphs_prose(sorted_blocks, page_height)
    
    # Assign each block to nearest column
    col_blocks_map = defaultdict(list)
    for b in sorted_blocks:
        x = block_center_x(b)
        nearest_col = min(columns, key=lambda c: abs(c - x))
        col_blocks_map[nearest_col].append(b)
    
    # Sort each column by y
    for col_x in col_blocks_map:
        col_blocks_map[col_x].sort(key=lambda b: block_top_y(b))
    
    # Leftmost column should contain No.xxxx anchors
    left_col_x = min(columns)
    left_blocks = col_blocks_map[left_col_x]
    
    # Collect all non-left-column blocks (right side entries)
    right_blocks = []
    for col_x, blist in col_blocks_map.items():
        if col_x != left_col_x:
            right_blocks.extend(blist)
    right_blocks.sort(key=lambda b: block_top_y(b))
    
    # Find anchor positions (No.xxxx blocks) in left column
    anchors = []
    for b in left_blocks:
        txt = b["text_raw"].strip()
        if re.match(r'^No[\.\s]?\d+', txt):
            anchors.append(b)
    
    if not anchors:
        # No anchors found — fallback
        return _assemble_paragraphs_prose(sorted_blocks, page_height)
    
    paragraphs = []
    
    # Blocks above the first anchor → separate paragraphs (titles etc.)
    first_anchor_y = block_top_y(anchors[0])
    above_anchors = [b for b in left_blocks if block_top_y(b) < first_anchor_y - PARA_MAX_GAP_Y]
    
    # Group above-anchor blocks into paragraphs (y-gap based)
    if above_anchors:
        above_anchors.sort(key=lambda b: (block_top_y(b), block_center_x(b)))
        current = [above_anchors[0]]
        for b in above_anchors[1:]:
            if block_top_y(b) - block_top_y(current[-1]) >= PARA_BREAK_GAP_Y:
                paragraphs.append(make_para_record(current))
                current = [b]
            else:
                current.append(b)
        paragraphs.append(make_para_record(current))
    
    # For each anchor, collect right-column blocks in its y-band
    for i, anchor in enumerate(anchors):
        anchor_y = block_top_y(anchor)
        # Next anchor's y (or infinity for last anchor)
        next_anchor_y = block_top_y(anchors[i + 1]) if i + 1 < len(anchors) else float('inf')
        # Extended band: from anchor_y down to just before next_anchor_y
        band_bottom = next_anchor_y - PARA_MAX_GAP_Y
        
        # Collect right-column blocks in this band
        entry_blocks = [anchor]
        for rb in right_blocks:
            rb_y = block_top_y(rb)
            if anchor_y - PARA_MAX_GAP_Y <= rb_y < band_bottom:
                entry_blocks.append(rb)
        
        # Sort entry blocks: group by visual line (floor-div y), then left-to-right (x)
        entry_blocks.sort(key=lambda b: (block_top_y(b) // PARA_MAX_GAP_Y, block_center_x(b)))
        
        if entry_blocks:
            paragraphs.append(make_para_record(entry_blocks))
    
    return paragraphs


def make_para_record(blocks):
    """Create a paragraph record from a list of blocks."""
    texts = [b["text_raw"] for b in blocks]
    full_text = "\n".join(texts)
    
    # Sort blocks by id within paragraph
    input_refs = [b["id"] for b in blocks]
    
    # Confidence: average of block confidences
    confidences = [b.get("confidence", 1.0) for b in blocks]
    avg_conf = sum(confidences) / len(confidences) if confidences else 1.0
    
    # Page indices
    page_indices = sorted(set(b["page_index"] for b in blocks))
    
    return {
        "input_refs": input_refs,
        "text": full_text,
        "confidence": round(avg_conf, 4),
        "page_indices": page_indices,
        "block_count": len(blocks),
        "char_count": len(full_text),
    }


# ─── Layer D: OCR Flags ───────────────────────────────────────────────────

def generate_ocr_flags(blocks):
    """Generate OCR quality flags for blocks with suspected issues."""
    flags = []
    
    for b in blocks:
        txt = b["text_raw"]
        conf = b.get("confidence", 1.0)
        
        block_flags = []
        
        # Low confidence
        if conf < 0.85:
            block_flags.append({"type": "low_confidence", "confidence": conf})
        
        # Suspected character confusions
        for wrong, right in OCR_CONFUSIONS.items():
            if wrong in txt:
                block_flags.append({"type": "suspected_error", "pattern": wrong, "suggestion": right})
        
        if block_flags:
            flags.append({
                "block_id": b["id"],
                "book_id": b["book_id"],
                "page_index": b["page_index"],
                "text": txt,
                "flags": block_flags,
            })
    
    return flags


# ─── Main Pipeline ────────────────────────────────────────────────────────

def process_book(book_id, blocks, output_dir):
    """Run the full pipeline on one book."""
    # Group by page
    pages = group_by_page(blocks)
    
    if not pages:
        print(f"  {book_id}: no blocks found", file=sys.stderr)
        return
    
    # Layer A: Detect running headers (needs all pages of the book)
    header_block_ids, header_texts = detect_running_headers(pages)
    
    if header_texts:
        print(f"  {book_id}: detected {len(header_block_ids)} header blocks, "
              f"{len(header_texts)} unique header positions", file=sys.stderr)
    
    # Calculate median block height (for section title detection)
    all_heights = [block_height(b) for b in blocks if block_height(b) < 200]
    median_height = statistics.median(all_heights) if all_heights else 35
    
    # Process each page using enhanced LayoutAnalyzer
    layout_analyzer = LayoutAnalyzer()
    known_headers = set(header_texts.values())

    all_page_structures = []
    all_paragraphs = []
    all_flags = []
    
    for pi in sorted(pages.keys()):
        page_blocks = pages[pi]
        page_h = detect_page_height(page_blocks)
        
        # Enhanced Layout Analysis: Span-banding, adaptive columns, heading hierarchy
        layout_res = layout_analyzer.analyze_page(
            page_blocks,
            page_height=page_h,
            known_running_header_texts=known_headers,
        )
        
        ps_meta = layout_res["page_structure"]
        paragraphs = layout_res["paragraphs"]
        
        # Add book_id and page_id to each paragraph
        for p_idx, p in enumerate(paragraphs):
            p["book_id"] = book_id
            p["page_index"] = pi
            p["para_index"] = p_idx
            p["section_title"] = ""
            if layout_res["headings"]:
                p["section_title"] = layout_res["headings"][0]["text"]
        
        # Page structure record
        page_struct = {
            "book_id": book_id,
            "page_index": pi,
            "block_count": len(page_blocks),
            "classified": {
                "body": sum(1 for b in layout_res["reading_order_blocks"] if b.get("role") == "body"),
                "heading": sum(1 for b in layout_res["reading_order_blocks"] if b.get("role") == "heading"),
                "running_header": len(ps_meta["running_headers"]),
                "page_number": len(ps_meta["page_numbers"]),
            },
            "columns": ps_meta["columns"],
            "column_x_positions": [round((r[0] + r[1]) / 2, 1) for r in ps_meta["column_ranges"]],
            "column_ranges": ps_meta["column_ranges"],
            "has_span_elements": ps_meta["has_span_elements"],
            "headings": ps_meta["headings"],
            "running_headers": [h["text"] for h in ps_meta["running_headers"]],
            "page_numbers": [pn["text"] for pn in ps_meta["page_numbers"]],
            "paragraph_count": len(paragraphs),
            "input_refs": [b.get("id", "") for b in page_blocks],
        }
        all_page_structures.append(page_struct)
        all_paragraphs.extend(paragraphs)
    
    # Layer D: OCR flags
    all_flags = generate_ocr_flags(blocks)
    
    # Write outputs
    book_dir = Path(output_dir) / book_id
    book_dir.mkdir(parents=True, exist_ok=True)
    
    with open(book_dir / "page_structure.jsonl", "w", encoding="utf-8") as f:
        for rec in all_page_structures:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    
    with open(book_dir / "paragraphs_v2.jsonl", "w", encoding="utf-8") as f:
        for i, rec in enumerate(all_paragraphs):
            rec["id"] = f"{book_id}:pi{rec.get('page_index','?')}:p{i}"
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    
    with open(book_dir / "ocr_flags.jsonl", "w", encoding="utf-8") as f:
        for rec in all_flags:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    
    # Doc meta with enhanced heading & column metrics
    total_headings = sum(len(ps["headings"]) for ps in all_page_structures)
    heading_level_counts = Counter()
    for ps in all_page_structures:
        for h in ps["headings"]:
            heading_level_counts[f"level_{h['level']}"] += 1

    doc_meta = {
        "book_id": book_id,
        "total_pages": len(pages),
        "total_blocks": len(blocks),
        "total_paragraphs": len(all_paragraphs),
        "total_headings": total_headings,
        "heading_level_distribution": dict(heading_level_counts),
        "total_flags": len(all_flags),
        "running_headers_detected": len(header_block_ids),
        "median_block_height": round(median_height, 1),
        "multi_column_pages": sum(1 for ps in all_page_structures if ps["columns"] > 1),
        "span_pages_count": sum(1 for ps in all_page_structures if ps["has_span_elements"]),
        "total_columns_observed": len(set(ps["columns"] for ps in all_page_structures)),
    }
    with open(book_dir / "doc_meta.json", "w", encoding="utf-8") as f:
        json.dump(doc_meta, f, ensure_ascii=False, indent=2)
    
    print(f"  {book_id}: {len(pages)} pages, {len(all_paragraphs)} paras, "
          f"{total_headings} headings, {len(all_flags)} flags", file=sys.stderr)
    
    return doc_meta



def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Rebuild navigation layer from blocks.jsonl using LayoutAnalyzer")
    parser.add_argument("--book-id", help="Process a single book ID")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of books to process")
    parser.add_argument("--output-dir", default="data/evidence/navigation", help="Output directory")
    args = parser.parse_args()

    blocks_dir = "data/evidence"
    output_dir = args.output_dir
    os.makedirs(output_dir, exist_ok=True)
    
    # Load blocks
    target_book = args.book_id
    if target_book:
        print(f"Loading blocks for single book '{target_book}' from all shards...", file=sys.stderr)
        blocks = load_blocks_for_book(target_book, [f"{blocks_dir}/shard{s}/blocks.jsonl" for s in range(1, 5)])
        if not blocks:
            print(f"Error: No blocks found for '{target_book}' in shards 1-4.", file=sys.stderr)
            sys.exit(1)
        print(f"Loaded {len(blocks)} blocks for '{target_book}'. Processing...", file=sys.stderr)
        meta = process_book(target_book, blocks, output_dir)
        print(f"Completed '{target_book}': {meta['total_pages']} pages, {meta['total_paragraphs']} paragraphs, {meta['total_headings']} headings.", file=sys.stderr)
        return

    print("Loading blocks from all shards...", file=sys.stderr)
    book_blocks = defaultdict(list)
    for shard_num in range(1, 5):
        path = f"{blocks_dir}/shard{shard_num}/blocks.jsonl"
        if not os.path.exists(path):
            print(f"  {path} not found, skip", file=sys.stderr)
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    b = json.loads(line)
                    book_blocks[b["book_id"]].append(b)
    
    print(f"Loaded {sum(len(v) for v in book_blocks.values())} blocks from {len(book_blocks)} books",
          file=sys.stderr)
    
    # Process each book
    all_meta = []
    book_ids = sorted(book_blocks.keys())
    if args.limit:
        book_ids = book_ids[:args.limit]
        print(f"Limiting to first {len(book_ids)} books.", file=sys.stderr)

    for book_id in book_ids:
        meta = process_book(book_id, book_blocks[book_id], output_dir)
        if meta:
            all_meta.append(meta)
    
    # Write global summary
    with open(Path(output_dir) / "pipeline_summary.json", "w", encoding="utf-8") as f:
        json.dump({
            "total_books": len(all_meta),
            "total_pages": sum(m["total_pages"] for m in all_meta),
            "total_paragraphs": sum(m["total_paragraphs"] for m in all_meta),
            "total_flags": sum(m["total_flags"] for m in all_meta),
            "total_running_header_blocks": sum(m["running_headers_detected"] for m in all_meta),
            "per_book": all_meta,
        }, f, ensure_ascii=False, indent=2)
    
    print(f"\nDone. Processed {len(all_meta)} books, "
          f"{sum(m['total_paragraphs'] for m in all_meta)} paragraphs, "
          f"{sum(m['total_flags'] for m in all_meta)} flags.",
          file=sys.stderr)


if __name__ == "__main__":
    main()
