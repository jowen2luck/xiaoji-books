#!/usr/bin/env python3
"""Test LayoutAnalyzer: Multi-Column Reading Order, Span Banding & Heading Levels."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.pipeline.layout_analyzer import LayoutAnalyzer

def test_layout_analyzer():
    analyzer = LayoutAnalyzer()

    # Test Case 1: Running Header + Span Heading + Two Column text + Subheading
    blocks = [
        # Running header at top
        {'text': '过渡时期经济学', 'box': [[200, 30], [400, 30], [400, 50], [200, 50]], 'id': 'b_hdr'},
        # Page number
        {'text': '12', 'box': [[50, 30], [70, 30], [70, 50], [50, 50]], 'id': 'b_pnum'},
        # Span Title (Full-width, Level 2 Chapter)
        {'text': '第一章 资本主义经济的转化过程', 'box': [[80, 100], [520, 100], [520, 140], [80, 140]], 'id': 'b_t1'},
        # Left Column Line 1
        {'text': '这是左栏第一行正文内容。', 'box': [[60, 180], [270, 180], [270, 210], [60, 210]], 'id': 'b_l1'},
        # Right Column Line 1 (Physically at same Y as left col)
        {'text': '这是右栏第一行正文内容。', 'box': [[330, 180], [540, 180], [540, 210], [330, 210]], 'id': 'b_r1'},
        # Left Column Line 2
        {'text': '这是左栏第二行正文内容。', 'box': [[60, 220], [270, 220], [270, 250], [60, 250]], 'id': 'b_l2'},
        # Right Column Line 2
        {'text': '这是右栏第二行正文内容。', 'box': [[330, 220], [540, 220], [540, 250], [330, 250]], 'id': 'b_r2'},
        # Span Sub-Heading in middle (Level 3 Section)
        {'text': '第一节 资本积累与商品流通', 'box': [[80, 290], [520, 290], [520, 325], [80, 325]], 'id': 'b_t2'},
        # Left Col under sub-heading
        {'text': '小节下左栏正文。', 'box': [[60, 350], [270, 350], [270, 380], [60, 380]], 'id': 'b_l3'},
        # Right Col under sub-heading
        {'text': '小节下右栏正文。', 'box': [[330, 350], [540, 350], [540, 380], [330, 380]], 'id': 'b_r3'},
    ]

    res = analyzer.analyze_page(blocks, page_width=600, page_height=800)

    print("=== Test Results ===")
    print("Columns detected:", res["page_structure"]["columns"])
    print("Has span elements:", res["page_structure"]["has_span_elements"])
    print("Headings detected:", len(res["headings"]))
    for h in res["headings"]:
        print(f"  [Level {h['level']}] {h['text']} ({h['category']})")

    print("\nReading order texts:")
    for p in res["paragraphs"]:
        role = f"[{p['role']} L{p.get('heading_level')}]" if p.get("is_heading") else "[body]"
        print(f"  {role} Col{p['column_idx']}: {p['text']}")

    expected_sequence = [
        "第一章 资本主义经济的转化过程",
        "这是左栏第一行正文内容。\n这是左栏第二行正文内容。",
        "这是右栏第一行正文内容。\n这是右栏第二行正文内容。",
        "第一节 资本积累与商品流通",
        "小节下左栏正文。",
        "小节下右栏正文。"
    ]

    actual_texts = [p["text"] for p in res["paragraphs"]]
    assert actual_texts == expected_sequence, f"Mismatch!\nExpected: {expected_sequence}\nActual: {actual_texts}"

    # Verify heading levels
    assert res["headings"][0]["level"] == 2  # 第一章 -> Level 2
    assert res["headings"][1]["level"] == 3  # 第一节 -> Level 3

    # Verify running headers and page numbers properly identified
    assert len(res["page_structure"]["running_headers"]) == 1
    assert res["page_structure"]["running_headers"][0]["text"] == "过渡时期经济学"
    assert len(res["page_structure"]["page_numbers"]) == 1
    assert res["page_structure"]["page_numbers"][0]["text"] == "12"

    print("\n[SUCCESS] All Reading Order, Multi-Column, Span-Title & Heading tests PASSED 100%!")


def test_real_pdf_ocr():
    from scripts.pipeline.ocr_extract import process_pdf_ocr
    import json

    pdf_path = Path(PROJECT_ROOT) / "data/_kage/www.marxists.org/chinese/bukharin/053103.pdf"
    if not pdf_path.exists():
        print(f"Skipping real PDF test: {pdf_path} does not exist.")
        return

    print("\n=== Testing Real PDF OCR with Integrated LayoutAnalyzer ===")
    res = process_pdf_ocr(
        str(pdf_path),
        book_id="test-bukharin",
        max_pages=2,
        return_blocks=True,
        analyze_layout=True,
    )

    assert len(res["pages"]) == 2
    for p in res["pages"]:
        pi = p["page_index"]
        col = p.get("columns", 1)
        h_cnt = len(p.get("headings", []))
        p_cnt = len(p.get("paragraphs", []))
        print(f"  Page {pi + 1}: {col} column(s), {h_cnt} heading(s), {p_cnt} paragraph(s)")
        for h in p.get("headings", []):
            print(f"    -> Heading L{h['level']}: {h['text']} ({h['category']}) | bbox: {h['bbox']}")

    print("[SUCCESS] Real PDF OCR + Layout Structuring executed smoothly!")


if __name__ == "__main__":
    test_layout_analyzer()
    test_real_pdf_ocr()

