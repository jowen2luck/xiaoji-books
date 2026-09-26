import fitz
import subprocess
import io
import tarfile
import time
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
pdf_path = ROOT / "data/_kage/www.marxists.org/chinese/pdf/chinese_marxists/mao/01210809.pdf"

doc = fitz.open(str(pdf_path))
tar_buf = io.BytesIO()
with tarfile.open(fileobj=tar_buf, mode="w") as tar:
    for p_idx in [2, 3]:
        pix = doc[p_idx].get_pixmap(dpi=150)
        img_bytes = pix.tobytes("png")
        ti = tarfile.TarInfo(name=f"p_{p_idx}.png")
        ti.size = len(img_bytes)
        tar.addfile(ti, io.BytesIO(img_bytes))
doc.close()
tar_data = tar_buf.getvalue()

remote_python = """
import sys, tarfile, io, subprocess, json, glob, os
data = sys.stdin.buffer.read()
tar = tarfile.open(fileobj=io.BytesIO(data))
tar.extractall('/data/data/com.termux/files/home/workspace/pipe_bench')
results = []
for f in sorted(glob.glob('/data/data/com.termux/files/home/workspace/pipe_bench/p_*.png')):
    p_num = int(os.path.basename(f).replace('p_', '').replace('.png', ''))
    r = subprocess.run(['tesseract', f, 'stdout', '-l', 'chi_sim', '--oem', '1'], capture_output=True, text=True)
    txt = r.stdout.strip()
    results.append({'page': p_num, 'chars': len(txt)})
    os.remove(f)
print(json.dumps(results))
"""

for name, ip in [("oppo-service", "192.168.2.60"), ("mon-worker", "192.168.2.62")]:
    t0 = time.time()
    try:
        r = subprocess.run(
            ["ssh", "-p", "8022", "-o", "ConnectTimeout=5", ip,
             f"export PATH=/data/data/com.termux/files/usr/bin:$PATH && mkdir -p ~/workspace/pipe_bench && python3 -c \"{remote_python}\""],
            input=tar_data, capture_output=True, text=False, timeout=30
        )
        print(f"[{name}] SUCCESS in {time.time()-t0:.2f}s | Output: {r.stdout.decode('utf-8', errors='ignore').strip()}")
    except Exception as e:
        print(f"[{name}] FAILED: {e}")
