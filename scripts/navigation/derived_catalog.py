"""Derived Catalog — infer table of contents from book pages (M4).

Strategy (priority order):
1. PDF bookmarks (pypdf)
2. 印刷目录页 (pages starting with "目录"/"CONTENTS")
3. Regex rules (章节 patterns)
4. Mark as low confidence if none of the above

All entries go into toc_derived (NOT toc_source) with confidence + provenance.
This layer is Navigation: can be deleted and rebuilt without touching Evidence.

Usage:
    python scripts/navigation/derived_catalog.py --db data/catalog/catalog.db
"""
import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

# Patterns for Chinese + English chapter headings
CHAPTER_PATTERNS = [
    # 中文数字第X篇/章/节/部分
    re.compile(r"第[零一二三四五六七八九十百千万\d]+[篇章节部分]\s*[、．.]?\s*(.+?)$", re.MULTILINE),
    # 中文数字X
    re.compile(r"(?<!\w)([零一二三四五六七八九十百千万\d]+)[、．.]+\s*(\S.{2,80}?)$", re.MULTILINE),
    # 1.2.3 or I.II.III patterns
    re.compile(r"(?<!\w)([IVXLCDM]+[\.\)]|[0-9]{1,2}(?:\.[0-9]{1,2}){0,3})[.\s]+(\S.{2,60}?)$", re.MULTILINE),
]

TOC_HEADER_PATTERNS = [
    re.compile(r"^[\s　]*(目\s*录|目\s*次|CONTENTS|Table\s+of\s*Contents)[\s　]*$", re.MULTILINE | re.IGNORECASE),
]


def extract_toc_from_pages(db_path: str) -> dict:
    """Extract derived table of contents from each book's pages.
    
    Returns {book_id: [{"title", "page_index", "level", "confidence", "provenance"}]}
    """
    conn = sqlite3.connect(db_path)
    
    # Get all books
    cur = conn.execute("SELECT book_id, page_count FROM books")
    books = cur.fetchall()
    
    results = {}
    
    for book_id, page_count in books:
        if not page_count:
            continue
        
        # Get pages in order
        cur = conn.execute("""
            SELECT page_index, text_normalized
            FROM pages
            WHERE book_id = ?
            ORDER BY page_index
        """, (book_id,))
        pages = cur.fetchall()
        
        if not pages:
            continue
        
        entries = []
        in_toc_section = False
        toc_page_count = 0
        
        for page_idx, text in pages:
            if not text:
                continue
            
            text_stripped = text.strip()
            
            # Check if we're hitting a TOC header
            for pat in TOC_HEADER_PATTERNS:
                if pat.search(text_stripped[:200]):  # Check start of page
                    in_toc_section = True
                    toc_page_count = 0
                    break
            
            if in_toc_section:
                toc_page_count += 1
                # Stop TOC section after 3 pages (typical TOC is 1-3 pages)
                if toc_page_count > 3:
                    in_toc_section = False
                    continue
                
                # Extract TOC entries from this page
                for pat in CHAPTER_PATTERNS:
                    for m in pat.finditer(text):
                        title = m.group(m.lastindex).strip()
                        if 3 < len(title) < 80 and not title.startswith(("http", "www.", "//")):
                            entries.append({
                                "title": title[:200],
                                "page_index": page_idx,
                                "level": 1,
                                "confidence": 0.75 if in_toc_section else 0.4,
                                "provenance": json.dumps({
                                    "generator": "derived_catalog_v1",
                                    "method": "page_text_regex",
                                    "in_toc_section": in_toc_section,
                                }),
                            })
            else:
                # Scan for chapter headings (lower confidence)
                for pat in CHAPTER_PATTERNS:
                    for m in pat.finditer(text):
                        title = m.group(m.lastindex).strip()
                        if 5 < len(title) < 60:
                            entries.append({
                                "title": title[:200],
                                "page_index": page_idx,
                                "level": 1,
                                "confidence": 0.35,
                                "provenance": json.dumps({
                                    "generator": "derived_catalog_v1",
                                    "method": "heading_regex_scan",
                                }),
                            })
        
        # Deduplicate by title (keep highest confidence)
        seen = {}
        for e in entries:
            t = e["title"]
            if t not in seen or e["confidence"] > seen[t]["confidence"]:
                seen[t] = e
        
        deduped = list(seen.values())
        if deduped:
            results[book_id] = deduped
    
    conn.close()
    return results


def write_derived_catalog(db_path: str, toc_data: dict):
    """Write derived TOC to catalog.db (toc_derived table), replacing all."""
    conn = sqlite3.connect(db_path)
    
    # Clear existing derived catalog for full rebuild
    conn.execute("DELETE FROM toc_derived")
    
    batch_count = 0
    for book_id, entries in toc_data.items():
        # Sort by page_index
        entries.sort(key=lambda e: (e.get("page_index", 0), -e.get("confidence", 0)))
        
        parent_stack = []  # (level, id) stack
        for i, entry in enumerate(entries):
            toc_id = f"tocd-{book_id}-{i:04d}"
            
            # Determine parent from level stack
            level = entry.get("level", 1)
            parent_id = None
            while parent_stack and parent_stack[-1][0] >= level:
                parent_stack.pop()
            if parent_stack:
                parent_id = parent_stack[-1][1]
            
            if level == 1 or not parent_id:
                parent_stack = [(level, toc_id)]
            else:
                parent_stack.append((level, toc_id))
            
            conn.execute("""
                INSERT INTO toc_derived
                    (id, book_id, page_index, printed_page, title, level, parent_id,
                     confidence, provenance)
                VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?)
            """, (
                toc_id,
                book_id,
                str(entry.get("page_index", 0) + 1),
                entry.get("title", ""),
                level,
                parent_id,
                entry.get("confidence", 0.0),
                entry.get("provenance", ""),
            ))
            batch_count += 1
    
    conn.commit()
    conn.close()
    return batch_count


def main():
    parser = argparse.ArgumentParser(description="Generate derived catalog from book pages")
    parser.add_argument("--db", default="data/catalog/catalog.db")
    args = parser.parse_args()
    
    if not Path(args.db).exists():
        print(f"ERROR: {args.db} does not exist. Run load_catalog.py first.", file=sys.stderr)
        sys.exit(1)
    
    print(f"Extracting derived TOC from {args.db}...", file=sys.stderr)
    toc_data = extract_toc_from_pages(args.db)
    
    book_count = len(toc_data)
    entry_count = sum(len(v) for v in toc_data.values())
    print(f"Found {entry_count} TOC entries across {book_count} books", file=sys.stderr)
    
    n = write_derived_catalog(args.db, toc_data)
    print(f"Wrote {n} derived TOC entries to catalog.db", file=sys.stderr)
    
    # Sample output
    if toc_data:
        for bid, entries in list(toc_data.items())[:3]:
            print(f"  {bid}: {len(entries)} entries", file=sys.stderr)
            for e in entries[:2]:
                print(f"    - {e['title'][:50]}", file=sys.stderr)


if __name__ == "__main__":
    main()
