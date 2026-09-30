#!/usr/bin/env python3
"""Deep spot-check of text quality - content pages focus."""
import json
import re
from collections import defaultdict

SHARD_PATHS = [
    "data/evidence/shard1/pages.jsonl",
    "data/evidence/shard2/pages.jsonl",
    "data/evidence/shard3/pages.jsonl",
    "data/evidence/shard4/pages.jsonl",
    "data/evidence/pages.jsonl",
]

all_pages = []
for path in SHARD_PATHS:
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    all_pages.append(json.loads(line))
    except FileNotFoundError:
        pass

print(f"Total pages loaded: {len(all_pages)}")

by_book = defaultdict(list)
for p in all_pages:
    by_book[p["book_id"]].append(p)

print(f"Total books: {len(by_book)}")
print()

# Detailed reading order analysis on content pages
def analyze_reading_order(bid, max_pages=10):
    """Check if text on content pages reads naturally."""
    if bid not in by_book:
        return
    book_pages = sorted(by_book[bid], key=lambda x: x["page_index"])
    
    # Find content pages (not TOC)
    content = []
    for p in book_pages[3:]:
        text = p.get("text_raw", "").strip()
        if not text:
            continue
        # Skip TOC-like pages (many short numbered entries)
        lines = [l for l in text.split("\n") if l.strip()]
        short_ratio = sum(1 for l in lines if len(l.strip()) < 15) / max(len(lines), 1)
        if short_ratio > 0.7 and len(lines) > 10:
            continue  # skip TOC
        if text.count("目录") > 2:
            continue
        content.append(p)
        if len(content) >= max_pages:
            break
    
    for p in content[:5]:
        text = p.get("text_raw", "")
        conf = p.get("confidence", 0)
        ext = p.get("extractor", "?")
        pi = p["page_index"]
        lines = text.split("\n")
        
        issues = []
        
        # 1. Reading order sanity: check for isolated fragments BEFORE main text
        first_meaningful = None
        for i, l in enumerate(lines):
            s = l.strip()
            if s and len(s) > 20:
                first_meaningful = i
                break
        if first_meaningful and first_meaningful > 3:
            issues.append(f"LINES_BEFORE_BODY({first_meaningful} short/isolated lines)")
        
        # 2. Page number mixed in body (number surrounded by text)
        for l in lines:
            s = l.strip()
            if s.isdigit() and 1 <= len(s) <= 4:
                issues.append(f"ISOLATED_PAGE_NUM({s})")
                break
        
        # 3. Header within body (running title mid-page)
        if len(lines) > 5:
            first = lines[0].strip()
            mid = [l.strip() for l in lines[2:-2]]
            if first in mid and len(first) < 30 and len(first) > 2:
                issues.append(f"HEADER_REPEATED_MID_PAGE[{first[:20]}]")
        
        # 4. Fragmented non-TOC: very short lines not archival
        short = sum(1 for l in lines if 0 < len(l.strip()) < 8)
        if len(lines) > 5 and short / len(lines) > 0.4:
            # Check if it's archival (numbered entries)
            numbered = sum(1 for l in lines if re.match(r'^[Nn]o[\.\s]?\d', l.strip()))
            if numbered < 3:
                issues.append(f"LINE_BREAK_ARTIFACTS({short} short lines)")
        
        # 5. Paragraph cross-page breaks: check if text starts/ends mid-sentence
        first_line = lines[0].strip() if lines else ""
        last_line = lines[-1].strip() if lines else ""
        if first_line and first_line[0] in "的了着过呢吧啊吗而但并就":
            if len(first_line) < 10:
                issues.append(f"CROSS_PAGE_START[{first_line[:15]}]")
        if last_line and last_line[-1] not in "。！？\"'）】》":
            if len(last_line) > 5:
                issues.append(f"CROSS_PAGE_END[{last_line[-15:]}]")
        
        # 6. Wrong reading order: mixed columns detect
        # Check if there are blocks at very different x-positions
        # We can detect this from page text by checking for repeated header
        
        tag = " | ".join(issues) if issues else "(clean)"
        print(f"  p{pi:3d} [{ext:22s}] conf={conf:.2f} lines={len(lines):3d}  {tag}")
        
        # Show first 200 chars
        preview = text[:200].replace("\n", " | ")
        print(f"    {preview}")
        
        # Show last 100 chars for cross-page check
        if last_line:
            tail = text[-100:].replace("\n", " | ")
            print(f"    ...{tail}")
        print()

# Diverse book sample
target_books = [
    ("book-07", "苏联历史档案(档案多栏)"),
    ("book-49", "列宁全集49(档案双栏)"),
    ("book-20200622j", "西班牙内战(西行正文)"),
    ("book-11-6", "欧洲共产主义(章节书)"),
    ("book-me45", "马恩全集说明(文献)"),
    ("book-111901", "山东土改文献(混合)"),
]

for bid, desc in target_books:
    print(f"\n{'='*60}")
    print(f"{bid} ({desc})")
    print(f"{'='*60}")
    analyze_reading_order(bid)

# Check some books from shard2/3/4
print(f"\n{'='*60}"), 
print("CROSS-SHARD: random content pages from other shards")
print(f"{'='*60}")

shard_books = [
    ("book-12", "西班牙内战(下)"),
    ("book-chen-2", "chen-2目录页?"),
    ("book-07-3", "book-07-3版本?"),
    ("book-080325", "080325"),
]

for bid, desc in shard_books:
    analyze_reading_order(bid, max_pages=3)
