#!/usr/bin/env python3
"""Mobile Workshop Remote Slot Worker.

Runs directly inside Termux on Android. Reads tar stream from stdin,
processes pages with native Tesseract 5.5.3, and prints JSON results to stdout.
"""
import glob
import io
import json
import os
import subprocess
import sys
import tarfile

def main():
    slot_id = sys.argv[1] if len(sys.argv) > 1 else "slot_1"
    workspace = f"/data/data/com.termux/files/home/workspace/{slot_id}"
    os.makedirs(workspace, exist_ok=True)

    # 1. Read in-memory tar stream from stdin
    data = sys.stdin.buffer.read()
    if not data:
        print(json.dumps([]))
        return

    tar = tarfile.open(fileobj=io.BytesIO(data))
    tar.extractall(workspace)

    # 2. Execute native Tesseract on extracted images
    results = []
    png_files = sorted(glob.glob(f"{workspace}/p_*.png"))
    for f in png_files:
        basename = os.path.basename(f)
        p_num = int(basename.replace("p_", "").replace(".png", ""))
        try:
            r = subprocess.run(
                ["tesseract", f, "stdout", "-l", "chi_sim", "--oem", "1"],
                capture_output=True, text=True, timeout=60
            )
            txt = r.stdout.strip()
            conf = 0.75 if len(txt) >= 30 else 0.20
            results.append({
                "page_index": p_num,
                "text_normalized": txt,
                "char_count": len(txt),
                "confidence": conf
            })
        except Exception as e:
            results.append({
                "page_index": p_num,
                "text_normalized": "",
                "char_count": 0,
                "confidence": 0.0,
                "error": str(e)
            })
        finally:
            if os.path.exists(f):
                os.remove(f)

    # 3. Print clean JSON to stdout
    print(json.dumps(results, ensure_ascii=False))

if __name__ == "__main__":
    main()
