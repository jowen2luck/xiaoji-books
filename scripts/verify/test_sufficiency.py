#!/usr/bin/env python3
"""Test the improved is_page_text_sufficient function."""
import sys, io
sys.stderr = io.StringIO()

from scripts.pipeline.text_extract import is_page_text_sufficient

cases = [
    # (name, text, expected)
    ("Label-only 53 chars", "Document ID: 112539   Total Pages: 460", False),
    ("Chinese theory text", "第一節 勞動價值理論\n馬克思的勞動價值理論是整個政治經濟學的基石。\n在他看來，商品的價值是由生產該商品所需要的社會必要勞動時間決定的。\n這一點區別了使用價值和交換價值：使用價值是商品滿足人類需要的能力，\n而交換價值則是商品在市場上與其他商品交換的比例。", True),
    ("English chapter", "Chapter 2: The Architecture of Power\nThis chapter examines how power operates within organizational structures.\nWe begin with a theoretical framework drawn from Foucault and Weber,\nthen apply it to three empirical case studies.", True),
    ("Empty string", "", False),
    ("Just a page number", "42", False),
    ("URL only", "https://www.example.com/document.pdf", False),
    ("Mix labels + content", "Page 5\nChapter 3\n這裡開始真正的文章內容，\n有足夠的中文字符才能通過檢測。\n至少要三行以上才算有意義的內容。", True),
]

all_ok = True
for name, text, expected in cases:
    result = is_page_text_sufficient(text)
    status = "PASS" if result == expected else "FAIL"
    if result != expected:
        all_ok = False
    print(f"  {status} | {name:30} -> got={result:5} expected={expected}")

print()
print("ALL TESTS PASSED" if all_ok else "SOME TESTS FAILED")
