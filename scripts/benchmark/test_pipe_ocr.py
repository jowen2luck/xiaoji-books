import fitz
import subprocess
import io
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
pdf_path = ROOT / "data/_kage/www.marxists.org/chinese/pdf/chinese_marxists/mao/01210809.pdf"

t0 = time.time()
doc = fitz.open(str(pdf_path))

# Render 2 pages in-memory to tar bytes
tar_buf = io.BytesIO()
with tarfile.open(fileobj=tar_buf, mode="w") as tar:
    for p_idx in [0, 1]:
        pix = doc[p_idx].get_pixmap(dpi=150)
        img_bytes = pix.tobytes("png")
        ti = tarfile.TarInfo(name=f"p_{p_idx}.png")
        ti.size = len(img_bytes)
        tar.addfile(ti, io.BytesIO(img_bytes))
doc.close()
tar_data = tar_buf.getvalue()
t_render = round(time.time() - t0, 3)

remote_python = """
import sys, tarfile, io, subprocess, json, glob, os

data = sys.stdin.buffer.read()
tar = tarfile.open(fileobj=io.BytesIO(data))
tar.extractall('/data/data/com.termux/files/home/workspace/pipe_test')

results = []
for f in sorted(glob.glob('/data/data/com.termux/files/home/workspace/pipe_test/p_*.png')):
    p_num = int(os.path.basename(f).replace('p_', '').replace('.png', ''))
    r = subprocess.run(['tesseract', f, 'stdout', '-l', 'chi_sim', '--oem', '1'], capture_output=True, text=True)
    txt = r.stdout.strip()
    results.append({'page_index': p_num, 'char_count': len(txt), 'preview': txt[:60].replace('\\n', ' ')})
    os.remove(f)

print(json.dumps(results, ensure_ascii=False))
"""

t1 = time.time()
res = subprocess.run(
    ["ssh", "-p", "8022", "-o", "ConnectTimeout=5", "192.168.2.56",
     f"export PATH=/data/data/com.termux/files/usr/bin:$PATH && mkdir -p ~/workspace/pipe_test && python3 -c \"{remote_python}\""],
    input=tar_data, capture_output=True, text=False, timeout=30
)
t_ssh = round(time.time() - t1, 2)

print(f"Render Time: {t_render}s | Remote Pipe OCR Time: {t_ssh}s")
print("Response:", res.stdout.decode("utf-8", errors="ignore").strip())
