#!/usr/bin/env python3
"""Spot-check extracted text quality across all books."""
import json
import sys
from collections import defaultdict

SHARD_PATHS = [
    "data/evidence/shard1/pages.jsonl",
    "data/evidence/shard2/pages.jsonl",
    "data/evidence/shard3/pages.jsonl",
    "data/evidence/shard4/pages.jsonl",
]

# Load all pages from all shards
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

# Organize by book
by_book = defaultdict(list)
for p in all_pages:
    by_book[p["book_id"]].append(p)

print(f"Total books: {len(by_book)}")
print()

# Sample books: pick diverse types
# Look at several books with different characteristics
sample_books = [
    ("book-07", "苏联历史档案选编第7卷 (档案/多栏)"),
    ("book-49", "列宁全集49卷 (档案/双栏)"),
    ("book-20200622j", "西班牙内战 (西行/目录型)"),
    ("book-11-6", "book-11-6 (未知类型)"),
    ("book-111901", "book-111901 (文献集)"),
    ("book-me45", "book-me45 (马恩文献)"),
]

all_issues = []

for bid, desc in sample_books:
    if bid not in by_book:
        print(f"  {bid} NOT FOUND in pages -- skip")
        continue
    book_pages = sorted(by_book[bid], key=lambda x: x["page_index"])
    # Pick content pages (skip 0-2 cover/toc)
    content = [p for p in book_pages[3:15] if p.get("text_raw", "").strip()]
    if not content:
        content = book_pages[1:6]
    
    print(f"===== {bid} ({desc}) | {len(book_pages)} pages =====")
    for p in content[:6]:
        text = p.get("text_raw", "")
        conf = p.get("confidence", 0)
        ext = p.get("extractor", "?")
        pi = p["page_index"]
        lines = [l for l in text.split("\n") if l.strip()]
        n_lines = len(lines)
        
        issues = []
        
        # 1. Many very short lines (fragmentation)
        short = sum(1 for l in lines if len(l.strip()) < 10)
        if n_lines > 0 and short / n_lines > 0.6:
            issues.append(f"FRAGMENTED({short}/{n_lines} short lines)")
        
        # 2. Isolated numbers (page refs)
        iso_nums = sum(1 for l in lines if l.strip().replace("-","").replace(".","").isdigit() and len(l.strip()) <= 6)
        if iso_nums >= 2:
            issues.append(f"PAGE_NUMBERS_INLINE({iso_nums})")
        
        # 3. Header repeated within text
        first = lines[0].strip() if lines else ""
        if first and sum(1 for l in lines if l.strip() == first) >= 2 and len(first) < 30:
            issues.append(f"REPEATED_HEADER[{first[:25]}]")
        
        # 4. Long unbroken text (missing paragraph breaks)
        longest = max((len(l) for l in lines), default=0)
        if n_lines <= 2 and len(text) > 300:
            issues.append(f"MISSING_PARAGRAPH_BREAKS(longest_line={longest})")
        
        # 5. Lines starting with numbers (archival entries mixed)
        numbered = sum(1 for l in lines if l.strip() and l.strip()[0].isdigit() and len(l.strip()) < 8)
        if numbered >= 3:
            issues.append(f"NUMBER_ENTRIES({numbered})")
        
        # 6. Suspicious single chars
        single = sum(1 for l in lines if len(l.strip()) == 1)
        if single > 0:
            issues.append(f"SINGLE_CHAR_LINES({single})")
        
        # 7. Running header candidates
        if first and ("第" in first and "卷" in first) or ("选编" in first):
            issues.append(f"RUNNING_HEADER_CANDIDATE")
        
        tag = " | ".join(issues) if issues else "(clean)"
        print(f"  p{pi:3d} [{ext:22s}] conf={conf:.2f} lines={n_lines:3d}  {tag}")
        
        # Show first 250 chars
        preview = text[:250].replace("\n", " | ")
        print(f"    {preview}")
        print()
        
        # Record for summary
        for iss in issues:
            all_issues.append((bid, pi, iss))
    print()

print(f"\n===== SUMMARY OF ISSUES FOUND =====")
issue_types = defaultdict(int)
for bid, pi, iss in all_issues:
    # Get base issue type
    base = iss.split("(")[0] if "(" in iss else iss.split("[")[0] if "[" in iss else iss
    issue_types[base] += 1

for itype, cnt in sorted(issue_types.items(), key=lambda x: -x[1]):
    print(f"  {itype}: {cnt} occurrences")
