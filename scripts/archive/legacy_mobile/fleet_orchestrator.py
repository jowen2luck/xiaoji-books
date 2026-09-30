#!/usr/bin/env python3
"""Mobile Fleet Orchestrator for Book Evidence & Discovery Ingestion.

Coordinates distributed ingestion across PC and 4 Mobile Fleet Nodes:
- OPPO (192.168.2.60:8022): Coordinator / Intermediate Worker
- VIVO (192.168.2.56:8022): High Performance OCR Worker
- MON Tablet (192.168.2.62:8022): Lightweight Worker
- KOB Tablet (192.168.2.61:8022): Lightweight Worker

Usage:
    # 1. Generate shards
    python scripts/pipeline/generate_fleet_shards.py

    # 2. Deploy and run node
    python scripts/pipeline/fleet_orchestrator.py --node oppo --sync --start
    python scripts/pipeline/fleet_orchestrator.py --node mon --sync --start

    # 3. Check status
    python scripts/pipeline/fleet_orchestrator.py --status

    # 4. Pull and merge
    python scripts/pipeline/fleet_orchestrator.py --pull --merge
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

NODES = {
    "oppo": {
        "name": "oppo-service",
        "ip": "192.168.2.60",
        "port": 8022,
        "shard": "shard_2_oppo.jsonl",
        "remote_dir": "~/workspace/shard_oppo"
    },
    "vivo": {
        "name": "vivo-worker",
        "ip": "192.168.2.56",
        "port": 8022,
        "shard": "shard_1_vivo.jsonl",
        "remote_dir": "~/workspace/shard_vivo"
    },
    "mon": {
        "name": "mon-worker",
        "ip": "192.168.2.62",
        "port": 8022,
        "shard": "shard_3_mon.jsonl",
        "remote_dir": "~/workspace/shard_mon"
    },
    "kob": {
        "name": "kob-worker",
        "ip": "192.168.2.61",
        "port": 8022,
        "shard": "shard_4_kob.jsonl",
        "remote_dir": "~/workspace/shard_kob"
    }
}


def run_ssh(node_cfg: dict, command: str, timeout: int = 30) -> Tuple[int, str]:
    ip = node_cfg["ip"]
    port = node_cfg["port"]
    cmd = [
        "ssh", "-p", str(port),
        "-o", "ConnectTimeout=5",
        "-o", "StrictHostKeyChecking=no",
        ip, command
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return res.returncode, res.stdout.strip() or res.stderr.strip()


def sync_node(node_key: str, limit: int = 0):
    root = Path(__file__).resolve().parent.parent.parent
    node = NODES[node_key]
    shard_file = root / "data" / "fleet_shards" / node["shard"]
    if not shard_file.exists():
        print(f"Shard file not found: {shard_file}", file=sys.stderr)
        return

    print(f"[{node['name']}] Preparing workspace on {node['ip']}:{node['port']}...")
    run_ssh(node, f"mkdir -p {node['remote_dir']}/scripts/pipeline")

    # Copy worker script
    worker_script = root / "scripts" / "pipeline" / "termux_node_worker.py"
    subprocess.run([
        "scp", "-P", str(node["port"]),
        str(worker_script), f"{node['ip']}:{node['remote_dir']}/termux_node_worker.py"
    ], check=True)

    # Read shard and sync needed PDFs
    with open(shard_file, encoding="utf-8") as f:
        books = [json.loads(line) for line in f if line.strip()]

    if limit > 0:
        books = books[:limit]

    # Write targeted shard for node
    tmp_shard = root / "data" / "fleet_shards" / f"deploy_{node_key}.jsonl"
    with open(tmp_shard, "w", encoding="utf-8") as f:
        for b in books:
            f.write(json.dumps(b, ensure_ascii=False) + "\n")

    subprocess.run([
        "scp", "-P", str(node["port"]),
        str(tmp_shard), f"{node['ip']}:{node['remote_dir']}/shard.jsonl"
    ], check=True)

    print(f"[{node['name']}] Syncing {len(books)} PDF files to device...")
    for idx, b in enumerate(books, 1):
        rel_path = b.get("source_path") or b.get("source_full_path")
        local_pdf = root / "data" / "_kage" / "www.marxists.org" / rel_path
        if not local_pdf.exists():
            local_pdf = root / rel_path
        if not local_pdf.exists():
            print(f"  [WARN] Missing: {local_pdf}")
            continue

        remote_target_dir = f"{node['remote_dir']}/{Path(rel_path).parent.as_posix()}"
        run_ssh(node, f"mkdir -p {remote_target_dir}")
        subprocess.run([
            "scp", "-P", str(node["port"]),
            str(local_pdf), f"{node['ip']}:{remote_target_dir}/"
        ], check=True)
        if idx % 5 == 0 or idx == len(books):
            print(f"  Synced {idx}/{len(books)} files...")

    print(f"[{node['name']}] Sync completed.")


def start_node(node_key: str, mode: str = "triage"):
    node = NODES[node_key]
    print(f"[{node['name']}] Starting worker in mode='{mode}'...")
    if mode == "triage":
        worker_args = f"--mode triage --node-id {node['name']} --shard-file shard.jsonl --base-dir . --output-dir evidence_out --checkpoint chk.jsonl"
    else:
        worker_args = f"--mode visual-ocr --node-id {node['name']} --chunk-file queue_{node_key}.jsonl --base-dir . --output-dir evidence_out --checkpoint chk.jsonl"

    cmd = (
        f"cd {node['remote_dir']} && "
        f"export PATH=/data/data/com.termux/files/usr/bin:$PATH && "
        f"( nohup python3 termux_node_worker.py {worker_args} </dev/null > worker.log 2>&1 & ) && disown"
    )
    code, out = run_ssh(node, cmd)
    print(f"[{node['name']}] Started (exit={code})")


def check_status():
    print("\n" + "=" * 65)
    print(f"{'Node':15s} {'IP:Port':20s} {'Progress':20s} {'Status':10s}")
    print("=" * 65)
    for k, node in NODES.items():
        try:
            cmd = f"cd {node['remote_dir']} 2>/dev/null && cat chk.jsonl 2>/dev/null | wc -l"
            code, out = run_ssh(node, cmd, timeout=5)
            done_count = int(out.strip()) if code == 0 and out.strip().isdigit() else 0

            # Check if running
            _, ps_out = run_ssh(node, "pgrep -f termux_node_worker.py || true", timeout=4)
            is_running = "RUNNING" if ps_out.strip() else "IDLE"

            print(f"{node['name']:15s} {node['ip'] + ':' + str(node['port']):20s} Done: {done_count:4d} books       {is_running:10s}")
        except Exception as e:
            print(f"{node['name']:15s} {node['ip'] + ':' + str(node['port']):20s} OFFLINE / TIMEOUT")
    print("=" * 65)


def pull_and_merge():
    root = Path(__file__).resolve().parent.parent.parent
    shards_dir = root / "data" / ".parallel_shards"
    shards_dir.mkdir(parents=True, exist_ok=True)

    for k, node in NODES.items():
        local_dest = shards_dir / f"shard_{k}"
        print(f"Pulling output from {node['name']}...")
        try:
            subprocess.run([
                "scp", "-P", str(node["port"]),
                "-o", "ConnectTimeout=4",
                "-o", "StrictHostKeyChecking=no",
                "-r",
                f"{node['ip']}:{node['remote_dir']}/evidence_out",
                str(local_dest)
            ], check=True)
            print(f"  Successfully pulled {node['name']} evidence.")
        except Exception as e:
            print(f"  [WARN] Could not pull from {node['name']}: {e}")

    # Run merge
    python_exe = sys.executable
    merge_script = root / "scripts" / "pipeline" / "batch_parallel.py"
    print("\nMerging all shards into data/evidence...")
    subprocess.run([python_exe, str(merge_script), "--merge", "--shards-dir", str(shards_dir)], check=True)


def main():
    parser = argparse.ArgumentParser(description="Mobile Fleet Orchestrator")
    parser.add_argument("--mode", choices=["triage", "visual-ocr"], default="triage",
                        help="Execution mode: 'triage' (Phase 1 text-layer) or 'visual-ocr' (Phase 2 page chunks)")
    parser.add_argument("--node", choices=list(NODES.keys()) + ["all"], help="Target node")
    parser.add_argument("--sync", action="store_true", help="Sync shard and PDFs to node")
    parser.add_argument("--limit", type=int, default=0, help="Limit books during sync")
    parser.add_argument("--start", action="store_true", help="Start worker on node")
    parser.add_argument("--status", action="store_true", help="Check fleet worker progress")
    parser.add_argument("--pull", action="store_true", help="Pull evidence shards from all nodes")
    parser.add_argument("--merge", action="store_true", help="Merge shards into data/evidence")

    args = parser.parse_args()

    if args.status:
        check_status()
        return

    if args.sync and args.node:
        target_nodes = list(NODES.keys()) if args.node == "all" else [args.node]
        for n in target_nodes:
            sync_node(n, limit=args.limit)

    if args.start and args.node:
        target_nodes = list(NODES.keys()) if args.node == "all" else [args.node]
        for n in target_nodes:
            start_node(n, mode=args.mode)

    if args.pull or args.merge:
        pull_and_merge()


if __name__ == "__main__":
    main()
