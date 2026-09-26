import subprocess
import concurrent.futures

nodes = [
    ('vivo-worker', '192.168.2.56'),
    ('oppo-service', '192.168.2.60'),
    ('mon-worker', '192.168.2.62'),
    ('kob-worker', '192.168.2.61'),
]

def check(n):
    name, ip = n
    cmd = [
        'ssh', '-p', '8022', '-o', 'ConnectTimeout=4', '-o', 'StrictHostKeyChecking=no', ip,
        'export PATH="/data/data/com.termux/files/usr/bin:$PATH" && '
        'echo -n "TESSERACT=" && which tesseract 2>/dev/null || echo "NONE" && '
        'echo -n "PYTHON=" && which python3 2>/dev/null || echo "NONE"'
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return (name, True, r.stdout.replace('\n', ' | ').strip())
    except Exception as e:
        return (name, False, str(e))

with concurrent.futures.ThreadPoolExecutor() as ex:
    results = list(ex.map(check, nodes))

for name, ok, out in results:
    print(f'[{name}] OK={ok} | {out}')
