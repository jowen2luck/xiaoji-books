import subprocess
import concurrent.futures

nodes = [
    ('vivo-worker', '192.168.2.56'),
    ('oppo-service', '192.168.2.60'),
    ('mon-worker', '192.168.2.62'),
    ('kob-worker', '192.168.2.61'),
]

def probe(n):
    name, ip = n
    cmd = [
        'ssh', '-p', '8022', '-o', 'ConnectTimeout=4', '-o', 'StrictHostKeyChecking=no', ip,
        'echo "USER=$(whoami)" && '
        'echo "BIN_PYTHON=$(ls /data/data/com.termux/files/usr/bin/python3 2>/dev/null)" && '
        'echo "BIN_TESS=$(ls /data/data/com.termux/files/usr/bin/tesseract 2>/dev/null)" && '
        'echo "BIN_PDF=$(ls /data/data/com.termux/files/usr/bin/pdftotext 2>/dev/null)"'
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
        return (name, True, r.stdout.replace('\n', ' | ').strip())
    except Exception as e:
        return (name, False, str(e))

with concurrent.futures.ThreadPoolExecutor() as ex:
    results = list(ex.map(probe, nodes))

for name, ok, out in results:
    print(f'[{name}] {out}')
