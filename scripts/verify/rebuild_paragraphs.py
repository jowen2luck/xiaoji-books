#!/usr/bin/env python3
"""
Paragraph & Chapter Rebuilder for book-library-scanner.

Reads existing page-level evidence from data/evidence/pages.jsonl
and rebuilds paragraph-level records with:
  - Proper paragraph boundaries (newline-based)
  - Chapter/section metadata
  - Better content structure for retrieval

Chapter patterns detected:
  - Chinese: 第X章, 第X节, 第X部分, 导言, 序言, 前言, 结语, 附录, 参考文献, 目录, 索引
  - English: Chapter N, Section N, Part N, Introduction, Preface, Conclusion, Appendix, Bibliography, Index
  - Numbered: 一、二、三、…, (一), （一）, 1., 1.1, I., II., A., B.
"""

import json
import re
import os
import sys
from pathlib import Path

# ─── Chapter patterns ────────────────────────────────────────
# 同时支持简体和繁体中文章节标题
CHAPTER_PATTERNS = [
    # Chinese: 第X章, 第X节 (支持 第壹章/第二章/第3章 etc.)
    (r'^第[一二三四五六七八九十百千萬零\d]+\s*[章部分篇編冊卷]\s*[：:．.]?\s*.*$', 'zh_main'),
    # Chinese: 序言, 导言, 前言, 结语, 跋 (简繁体)
    (r'^(序言|導言|前言|原序|譯者序|译者序|自序|代序|緒論|绪论|结语|後記|后记|'
     r'附錄|附录|注释|參考文獻|参考文献|译名對照表|译名对照表|索引|目錄|目录|'
     r'編后记|编后记|弁言|凡例|跋|楔子|尾聲|尾声|结語|结语|后序|題辭|题辞)$', 'zh_special'),
    # Numbered Chinese enumeration mark: 一、二、三... (also 壹、贰)
    (r'^[（(]?[一二三四五六七八九十百千萬贰叁肆]+[）)]\s*[、．.]?\s*\S.{1,60}', 'zh_enum'),
    # English: Chapter N, Part N, Section N, etc.
    (r'^(Chapter|Part|SECTION|Section|Book|Volume)\s+[IVXLCDM\d]+\s*[：:．.\-]?\s*\S.*$', 'en_main'),
    # English special sections
    (r'^(Introduction|Preface|Foreword|Prologue|Epilogue|Conclusion|Appendix|Bibliography|'
     r'Index|Afterword|References|Acknowledgments?|Contents|Glossary)$', 'en_special'),
    # Numbered decimal: 1. Introduction / 1.1 Section (must NOT contain commas = avoid citation refs)
    (r'^\d+\.\s+[A-Z\u4e00-\u9fff][^,()]{2,60}$', 'numbered_title'),
    # Roman numerals: I., II., A., B.
    (r'^[IVXLCDM]{1,5}\.\s+\S.{2,60}$', 'roman_title'),
]

COMPILED_PATTERNS = [(re.compile(p, re.IGNORECASE), cat) for p, cat in CHAPTER_PATTERNS]


def is_chapter_title(line: str) -> tuple:
    """
    Check if a line looks like a chapter/section title.
    Returns (is_chapter, category, clean_title) or (False, "", "").
    """
    stripped = line.strip()
    if not stripped:
        return False, "", ""
    if len(stripped) > 120:
        return False, "", ""

    for regex, category in COMPILED_PATTERNS:
        if regex.match(stripped):
            return True, category, stripped

    return False, "", ""


def _line_is_chapter_heading(line: str) -> tuple:
    """Check if a single line looks like a chapter heading. Returns (True, category, title) or (False, '', '')."""
    stripped = line.strip()
    if not stripped or len(stripped) > 120:
        return False, "", ""
    for regex, category in COMPILED_PATTERNS:
        if regex.match(stripped):
            return True, category, stripped
    return False, "", ""


def split_text_to_paragraphs(text: str) -> list:
    """
    Split page text into meaningful paragraphs.

    Strategy:
      1. Split on double-newlines (explicit paragraph breaks from PDF)
      2. For blocks > 300 chars, inspect each single-newline line:
         - If a line matches a chapter heading pattern, split before it
         - Blank lines also cause splits
      3. Short blocks are kept as-is
    """
    if not text or not text.strip():
        return []

    # Normalize whitespace
    text = text.replace('\r\n', '\n').replace('\r', '\n')

    # First pass: split on multiple newlines
    raw_blocks = re.split(r'\n\s*\n', text)

    paragraphs = []
    for block in raw_blocks:
        block = block.strip()
        if not block:
            continue
        if len(block) > 300:
            # Scan lines for chapter headings — split when found
            sub_lines = block.split('\n')
            current = ""
            for line in sub_lines:
                stripped_line = line.strip()
                if not stripped_line:
                    if current:
                        paragraphs.append(current)
                        current = ""
                    continue
                is_chapter, _, _ = _line_is_chapter_heading(stripped_line)
                if is_chapter and current:
                    # Flush current content, then start new para with this heading
                    paragraphs.append(current)
                    current = stripped_line
                elif current:
                    current += "\n" + stripped_line
                else:
                    current = stripped_line
            if current:
                paragraphs.append(current)
        else:
            paragraphs.append(block)

    return [p for p in paragraphs if p.strip()]


def rebuild_paragraphs_for_page(page_record: dict) -> list:
    """
    Given a page record from evidence/pages.jsonl,
    produce a list of paragraph records with chapter metadata.
    """
    book_id = page_record.get("book_id", "")
    page_id = page_record.get("id", "")
    page_index = page_record.get("page_index", 0)
    evidence_set_id = page_record.get("evidence_set_id", "")
    artifact_id = page_record.get("artifact_id", "")
    text = page_record.get("text_normalized", "") or page_record.get("text_raw", "")

    if not text.strip():
        return []

    # Split into paragraphs
    para_texts = split_text_to_paragraphs(text)
    if not para_texts:
        return []

    paragraphs = []
    current_chapter = ""
    current_chapter_category = ""

    for i, para_text in enumerate(para_texts):
        # Check if this paragraph starts with a chapter title
        lines = para_text.split('\n')
        first_line = lines[0].strip() if lines else ""

        is_chapter, category, clean_title = is_chapter_title(first_line)

        if is_chapter:
            current_chapter = clean_title
            current_chapter_category = category

            # If the paragraph has more content after the title line,
            # keep the remaining content as the paragraph text
            if len(lines) > 1:
                para_text = '\n'.join(lines[1:]).strip()
            elif len(para_text) > len(first_line) + 10:
                # Title and content on same line
                para_text = para_text[len(first_line):].strip()
            else:
                # Only a chapter title - make it a standalone paragraph
                para_text = clean_title

        para_id = f"{page_id}:para{i}"

        char_start = text.find(para_text[:20]) if para_text else 0
        if char_start < 0:
            char_start = 0

        para_record = {
            "id": para_id,
            "book_id": book_id,
            "page_id": page_id,
            "page_index": page_index,
            "evidence_set_id": evidence_set_id,
            "char_start": char_start,
            "char_end": char_start + len(para_text),
            "text_normalized": para_text,
            "is_chapter_heading": is_chapter,
            "chapter_title": current_chapter if current_chapter else "",
            "chapter_category": current_chapter_category if current_chapter_category else "",
        }

        paragraphs.append(para_record)

    return paragraphs


def rebuild_all_paragraphs(
    pages_input: str = "data/evidence/pages.jsonl",
    output_path: str = "data/evidence/paragraphs_rebuilt.jsonl",
):
    """
    Rebuild all paragraphs from the page-level evidence.
    """
    pages_path = Path(pages_input)
    if not pages_path.exists():
        print(f"Input not found: {pages_input}", file=sys.stderr)
        return

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total_pages = 0
    total_paragraphs = 0
    chapter_count = 0
    books = set()

    with open(pages_path, "r", encoding="utf-8") as fin, \
         open(out_path, "w", encoding="utf-8") as fout:

        for line in fin:
            line = line.strip()
            if not line:
                continue

            try:
                page = json.loads(line)
            except json.JSONDecodeError:
                continue

            total_pages += 1
            books.add(page.get("book_id", ""))

            # Skip empty pages
            text = page.get("text_normalized", "") or page.get("text_raw", "")
            if not text.strip():
                continue

            paragraphs = rebuild_paragraphs_for_page(page)
            for para in paragraphs:
                total_paragraphs += 1
                if para.get("is_chapter_heading"):
                    chapter_count += 1
                fout.write(json.dumps(para, ensure_ascii=False) + "\n")

    print(f"Pages processed: {total_pages}", file=sys.stderr)
    print(f"Books: {len(books)}", file=sys.stderr)
    print(f"Total paragraphs: {total_paragraphs}", file=sys.stderr)
    print(f"Chapter headings found: {chapter_count}", file=sys.stderr)
    print(f"Output: {output_path}", file=sys.stderr)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Rebuild paragraphs with chapter metadata")
    parser.add_argument("--input", default="data/evidence/pages.jsonl",
                       help="Input pages.jsonl file")
    parser.add_argument("--output", default="data/evidence/paragraphs_rebuilt.jsonl",
                       help="Output paragraphs file")
    args = parser.parse_args()

    rebuild_all_paragraphs(args.input, args.output)


if __name__ == "__main__":
    main()
