"""Test RapidOCR (ONNX runtime, pure CPU) - fallback for PaddlePaddle oneDNN incompatibility."""

import os
import sys

print("=== Step 1: pdf2image ===")
from pdf2image import convert_from_path
pdf_path = r"D:\Pcode\play\_skills\book-library-skill\data\_kage\www.marxists.org\chinese\bukharin\053103.pdf"
images = convert_from_path(pdf_path, first_page=80, last_page=80, dpi=200)
print(f"Converted OK: {images[0].size}")

print("\n=== Step 2: RapidOCR (ONNX) ===")
from rapidocr_onnxruntime import RapidOCR

engine = RapidOCR()
print(f"RapidOCR initialized")

import tempfile
tmp = tempfile.mktemp(suffix=".png")
images[0].save(tmp)

result, elapse = engine(tmp)

if result:
    total_time = elapse[0] if isinstance(elapse, list) else elapse
    print(f"OCR found {len(result)} text lines:")
    for item in result:
        box = item[0]
        text = item[1]
        score = item[2]
        print(f"  [{score:.2f}] {text}")
    print(f"\nOCR ENGINE: rapidocr_onnxruntime (CPU ONNX)")
    print(f"Total inference time per page")
else:
    print("OCR returned no text")

os.unlink(tmp)
print("\nOCR TEST COMPLETE")
