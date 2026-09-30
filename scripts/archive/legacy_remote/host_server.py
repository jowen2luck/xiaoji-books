#!/usr/bin/env python3
"""主机端 HTTP 文件服务器 + 结果收集器。
- 暴露 D:\Pcode\play\_skills\book-library-skill 为静态文件服务
- POST /api/result 接收笔记本发回的 OCR 结果并写入 evidence/shard3/checkpoint
- POST /api/progress 接收心跳

用法:
    python scripts/remote/host_server.py
"""
import json
import os
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# --- 配置 ---
BASE_DIR = Path(r"D:\Pcode\play\_skills\book-library-skill")
PORT = 8899
SHARD3_DIR = BASE_DIR / "data/evidence/shard3"
SHARD4_DIR = BASE_DIR / "data/evidence/shard4"
SHARD3_DIR.mkdir(parents=True, exist_ok=True)
SHARD4_DIR.mkdir(parents=True, exist_ok=True)

# 安全：只允许访问 BASE_DIR 下文件
ALLOWED_PREFIX = BASE_DIR.resolve()


def _safe_path(url_path: str) -> Path | None:
    """解析 URL 路径为安全本地路径，阻止目录穿越。"""
    if not url_path or url_path == "/":
        return None
    # 去掉前导 / 和 URL 解码
    from urllib.parse import unquote
    rel = unquote(url_path.lstrip("/"))
    full = (BASE_DIR / rel).resolve()
    # 安全检查
    try:
        full.relative_to(ALLOWED_PREFIX)
    except ValueError:
        return None
    return full


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # 自定义日志格式（含来源 IP）
        sys.stderr.write(f"[{self.client_address[0]}] {format % args}\n")

    def _send_json(self, code: int, data: dict):
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        # 心跳
        if parsed.path == "/api/ping":
            return self._send_json(200, {"status": "ok", "base": str(BASE_DIR)})
        # manifest 下载
        if parsed.path == "/api/manifest/shard3":
            mf = BASE_DIR / "data/.shards/shard-3/manifest.jsonl"
            if mf.exists():
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.send_header("Content-Length", str(mf.stat().st_size))
                self.end_headers()
                self.wfile.write(mf.read_bytes())
            else:
                self._send_json(404, {"error": "shard-3 manifest not found"})
            return
        if parsed.path == "/api/manifest/shard4":
            mf = BASE_DIR / "data/.shards/shard-4/manifest.jsonl"
            if mf.exists():
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.send_header("Content-Length", str(mf.stat().st_size))
                self.end_headers()
                self.wfile.write(mf.read_bytes())
            else:
                self._send_json(404, {"error": "shard-4 manifest not found"})
            return

        # 静态文件服务（暴露 data/_kage、scripts 等）
        path = _safe_path(parsed.path)
        if path is None or not path.exists() or path.is_dir():
            self._send_json(404, {"error": "not found", "path": parsed.path})
            return
        self.send_response(200)
        ctype = "application/octet-stream"
        if path.suffix == ".pdf": ctype = "application/pdf"
        elif path.suffix in (".py", ".bat", ".json", ".txt"): ctype = "text/plain"
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(path.stat().st_size))
        self.end_headers()
        self.wfile.write(path.read_bytes())

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        parsed = urlparse(self.path)

        if parsed.path == "/api/progress":
            # 笔记本心跳 / 进度上报
            try:
                msg = json.loads(body)
                book_id = msg.get("book_id", "?")
            except Exception:
                book_id = "parse_error"
            return self._send_json(200, {"received": True, "book": book_id})

        if parsed.path in ("/api/shard3/books", "/api/shard3/pages", "/api/shard3/paragraphs",
                          "/api/shard4/books", "/api/shard4/pages", "/api/shard4/paragraphs"):
            # 写结果 JSONL（追加）
            parts = parsed.path.strip("/").split("/")
            shard = parts[1]  # shard3 or shard4
            rtype = parts[2]  # books/pages/paragraphs
            out_dir = SHARD3_DIR if shard == "shard3" else SHARD4_DIR
            out = out_dir / f"{rtype}.jsonl"
            written = 0
            with open(out, "ab") as f:
                for line in body.split(b"\n"):
                    line = line.strip()
                    if line:
                        f.write(line + b"\n")
                        written += 1
            self._send_json(200, {"written": written})
            return

        if parsed.path in ("/api/shard3/checkpoint", "/api/shard4/checkpoint"):
            parts = parsed.path.strip("/").split("/")
            shard = parts[1]
            out_dir = SHARD3_DIR if shard == "shard3" else SHARD4_DIR
            out = out_dir / "checkpoint.jsonl"
            with open(out, "ab") as f:
                for line in body.split(b"\n"):
                    line = line.strip()
                    if line:
                        f.write(line + b"\n")
            self._send_json(200, {"received": True})
            return

        self._send_json(400, {"error": "unknown endpoint", "path": parsed.path})


def main():
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[host_server] Serving {BASE_DIR} on http://0.0.0.0:{PORT}")
    print(f"[host_server] Shard3 out: {SHARD3_DIR}")
    print(f"[host_server] Shard4 out: {SHARD4_DIR}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[host_server] Stopped.")


if __name__ == "__main__":
    main()
