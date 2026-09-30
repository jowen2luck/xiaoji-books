#!/usr/bin/env python3
"""
schedule_daemon.py — Background countdown daemon to trigger batch OCR at 01:30 AM.
"""

import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
import subprocess

TARGET_TIME_STR = "2026-09-29 01:30:00"
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
BATCH_SCRIPT = ROOT_DIR / "run_ocr_batch.bat"
LOG_DIR = ROOT_DIR / "data/.ocr_reprocess"
LOCK_FILE = LOG_DIR / "ocr_batch.lock"
DAEMON_LOG = LOG_DIR / "schedule_daemon.log"


def log(msg: str):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{now_str}] {msg}"
    print(line, flush=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(DAEMON_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def is_already_running() -> bool:
    if not LOCK_FILE.exists():
        return False
    try:
        with open(LOCK_FILE, "r") as f:
            pid = int(f.read().strip())
        import psutil
        return psutil.pid_exists(pid)
    except Exception:
        return False


def main():
    target_dt = datetime.strptime(TARGET_TIME_STR, "%Y-%m-%d %H:%M:%S")
    now = datetime.now()
    wait_seconds = (target_dt - now).total_seconds()

    log(f"Schedule daemon started. Target time: {TARGET_TIME_STR}")

    if wait_seconds > 0:
        mins = wait_seconds / 60.0
        log(f"Waiting {wait_seconds:.0f}s (~{mins:.1f} minutes) until 01:30:00...")
        time.sleep(wait_seconds)

    log("Target time (01:30:00) reached! Checking batch execution state...")

    # Avoid duplicate concurrent execution if Windows Task Scheduler already started it
    if is_already_running():
        log("Batch process is already actively running (lockfile present). Daemon task completed.")
        return

    # Check if a python batch_ocr_unprocessed is already in process list
    try:
        import psutil
        for p in psutil.process_iter(['name', 'cmdline']):
            cmdline = " ".join(p.info.get('cmdline') or [])
            if "batch_ocr_unprocessed.py" in cmdline:
                log(f"Found active batch_ocr_unprocessed process (PID {p.pid}). No duplicate launch needed.")
                return
    except Exception:
        pass

    log(f"Launching {BATCH_SCRIPT} now...")
    try:
        with open(LOG_DIR / "ocr_run.log", "a", encoding="utf-8") as log_f:
            log_f.write(f"\n======================================================\n")
            log_f.write(f"SCHEDULED BATCH OCR TRIGGERED AT {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            log_f.write(f"======================================================\n")
            log_f.flush()

            proc = subprocess.Popen(
                [str(BATCH_SCRIPT)],
                cwd=str(ROOT_DIR),
                stdout=log_f,
                stderr=subprocess.STDOUT,
                shell=True
            )
            log(f"Batch script spawned with PID {proc.pid}.")
    except Exception as e:
        log(f"Error launching batch script: {e}")


if __name__ == "__main__":
    main()
