#!/usr/bin/env python3
"""Multi-column reading order analysis using block coordinates."""
import json
from collections import defaultdict, Counter
import statistics

SHARD_PATHS = [
    "data/evidence/shard1/blocks.jsonl",
    "data/evidence/shard2/blocks.jsonl",
    "data/evidence/shard3/blocks.jsonl",
    "data/evidence/shard4/blocks.jsonl",
]

all_blocks = []
for path in SHARD_PATHS:
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    all_blocks.append(json.loads(line))
    except FileNotFoundError:
        pass

print(f"Total blocks loaded: {len(all_blocks)}")

by_book = defaultdict(list)
for b in all_blocks:
    by_book[b["book_id"]].append(b)

def analyze_multicolumn(bid, sample_pages=5):
    """Analyze column structure and reading order issues."""
    if bid not in by_book:
        return
    book_blocks = by_book[bid]
    by_page = defaultdict(list)
    for b in book_blocks:
        by_page[b["page_index"]].append(b)
    
    # Sample pages - pick some from middle
    all_page_indices = sorted(by_page.keys())
    mid = len(all_page_indices) // 2
    sample = all_page_indices[mid:mid+sample_pages]
    
    print(f"\n===== {bid} | multi-column analysis =====")
    
    for pi in sample:
        page_blocks = by_page[pi]
        if len(page_blocks) < 5:
            continue
        
        # Get x-positions
        xs = [b["box"][0][0] for b in page_blocks]
        ys = [b["box"][0][1] for b in page_blocks]
        
        # Histogram of x-positions to find columns
        x_hist = Counter()
        for x in xs:
            bucket = round(x / 80) * 80  # 80px buckets
            x_hist[bucket] += 1
        
        # Sort columns by x-position
        cols = sorted(x_hist.items(), key=lambda x: x[0])
        n_cols = sum(1 for _, c in cols if c >= 3)  # meaningful columns
        
        # Check reading order issue
        # Sort by (y, x) and see if column order natural
        yx_sorted = sorted(page_blocks, key=lambda b: (b["box"][0][1], b["box"][0][0]))
        xy_sorted = sorted(page_blocks, key=lambda b: (b["box"][0][0], b["box"][0][1]))
        
        yx_text = " ".join(b["text_raw"][:10] for b in yx_sorted[:5])
        xy_text = " ".join(b["text_raw"][:10] for b in xy_sorted[:5])
        
        # Extract column positions
        if len(cols) >= 2:
            meaningful = [(x, c) for x, c in cols if c >= 3]
            if len(meaningful) >= 2:
                x_positions = [x for x, c in meaningful[:4]]
                col_info = f"cols={x_positions}"
            else:
                col_info = f"sparse_cols={[x for x,c in cols[:4]]}"
        else:
            col_info = f"single_col"
        
        print(f"  p{pi:3d} blocks={len(page_blocks):3d} x_range=[{min(xs):.0f}-{max(xs):.0f}] {col_info}")
        print(f"    y,x order first 5: {yx_text[:80]}")
        print(f"    x,y order first 5: {xy_text[:80]}")
        
        # Check for page number / header artifacts at page edges
        edge_blocks = [b for b in page_blocks if b["box"][0][0] < 150 or b["box"][0][0] > 900]
        if edge_blocks:
            edge_texts = [f'{b["text_raw"][:20]}(x={b["box"][0][0]:.0f})' for b in edge_blocks[:5]]
            print(f"    EDGE BLOCKS: {' | '.join(edge_texts)}")
        print()

def detect_running_headers(bid):
    """Detect text repeated across pages at same y-position (likely headers)."""
    if bid not in by_book:
        return
    book_blocks = by_book[bid]
    by_page = defaultdict(list)
    for b in book_blocks:
        by_page[b["page_index"]].append(b)
    
    # Group blocks by position bucket and check repetition
    # Key: (y_bucket, round(x/50)*50) -> set of (text, page_index)
    pos_text_map = defaultdict(set)
    
    all_page_indices = sorted(by_page.keys())
    for pi in all_page_indices:
        for b in by_page[pi]:
            y_b = round(b["box"][0][1] / 15) * 15
            x_b = round(b["box"][0][0] / 50) * 50
            pos_text_map[(y_b, x_b)].add((b["text_raw"], pi))
    
    # Find texts that appear at same position across many pages
    running = []
    for (y_b, x_b), text_page_set in pos_text_map.items():
        texts = defaultdict(set)
        for txt, pi in text_page_set:
            texts[txt].add(pi)
        for txt, pages in texts.items():
            if len(pages) >= 10 and 2 <= len(txt) <= 40:
                running.append((len(pages), y_b, x_b, txt))
    
    running.sort(reverse=True)
    if running:
        print(f"\n===== {bid} | RUNNING HEADERS (same pos, >10 pages) =====")
        for count, y, x, txt in running[:8]:
            print(f"  y={y:6.0f} x={x:6.0f} count={count:3d} [{txt}]")

# Analyze several books for multi-column issues
print("=" * 70)
print("MULTI-COLUMN READING ORDER ANALYSIS")
print("=" * 70)

multicol_books = [
    "book-07",   # 苏联历史档案
    "book-49",   # 列宁全集
    "book-11-6", # 欧洲共产主义
    "book-12",   # shard2
    "book-07-3", # shard3
    "book-07-2", # shard4
]

for bid in multicol_books:
    analyze_multicolumn(bid, sample_pages=4)

# Running header detection
print("\n" + "=" * 70)
print("RUNNING HEADER DETECTION")
print("=" * 70)

header_books = [
    "book-07",
    "book-49",
    "book-11-6",
    "book-me45",
    "book-111901",
]

for bid in header_books:
    detect_running_headers(bid)

# OCR error detection - find suspicious character substitutions
print("\n" + "=" * 70)
print("OCR ERROR DETECTION (common confusions)")
print("=" * 70)

# Known OCR confusions
confusion_patterns = [
    (r"榕琅", "喀琅施塔得"),
    (r"账", "目录的碎片"),
    (r"象含", "像含"),
    (r"双類", "双颊"),
    (r"B\n账", "可能为'目录'碎片或OCR噪声"),
    (r"精作了一里子", "可能为OCR错误"),
    (r"车轮滚的", "可能为OCR错误"),
    (r"列宁余集", "可能为'列宁全集'"),
    (r"怕内特", "伯内特"),
]

# Search for known issues
found_errors = defaultdict(list)
for b in all_blocks:
    txt = b["text_raw"]
    for pattern, correction in confusion_patterns:
        if pattern in txt:
            found_errors[pattern].append((b.get("book_id"), b["page_index"], txt[:50]))

for pattern, correction in confusion_patterns:
    if pattern in found_errors:
        items = found_errors[pattern]
        print(f"\n  PATTERN [{pattern}] -> {correction}")
        print(f"    Found in {len(items)} blocks:")
        bid_counter = Counter(item[0] for item in items)
        for bid, cnt in bid_counter.most_common(5):
            print(f"      {bid}: {cnt} times")

print("\nDone.")
