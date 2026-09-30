#!/usr/bin/env python3
"""
笔记本端 HTTP OCR worker。

工作流程:
  1. 从主机 HTTP API 下载 shard manifest（书本清单）
  2. 每本书：从主机下载 PDF 到本地临时目录
  3. 本地 OCR 处理（复用 batch_ingest 的 process_one_book）
  4. POST 结果 + checkpoint 回主机

用法:
    python scripts/remote/notebook_http_worker.py --shard 3
    python scripts/remote/notebook_http_worker.py --shard 4
"""
import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from datetime import datetime, timezone


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class HttpWorker:
    def __init__(self, host: str, port: int, shard: int):
        self.base_url = f"http://{host}:{port}"
        self.shard = shard
        self.temp_dir = Path(tempfile.mkdtemp(prefix=f"ocr_shard{shard}_"))
        self.stats = {"success": 0, "error": 0, "skip": 0}

    def _get(self, path, accept="application/json"):
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, headers={"Accept": accept})
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.read()

    def _post(self, path, data: bytes | dict):
        if isinstance(data, dict):
            data = json.dumps(data).encode("utf-8")
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/x-ndjson", "Accept": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()

    def fetch_manifest(self) -> list[dict]:
        """从主机下载 shard manifest（NDJSON 每行一本书）"""
        raw = self._get(f"/api/manifest/shard{self.shard}", accept="application/x-ndjson")
        books = []
        for line in raw.decode("utf-8").strip().split("\n"):
            line = line.strip()
            if line:
                try:
                    books.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return books

    def download_pdf(self, book: dict) -> str | None:
        """下载 PDF 到本地临时目录，返回本地路径。"""
        rel = book.get("source_full_path") or book.get("source_path")
        if not rel:
            return None
        # URL 里用正斜杠
        rel_url = rel.replace("\\", "/")
        url = f"{self.base_url}/data/{rel_url}"
        local_path = self.temp_dir / f"{book['book_id']}.pdf"
        if local_path.exists():
            return str(local_path)
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=300) as resp:
                local_path.write_bytes(resp.read())
            return str(local_path)
        except Exception as e:
            print(f"  [WARN] download failed: {e}", file=sys.stderr)
            return None

    def ocr_one_book(self, pdf_path: str, book: dict) -> dict:
        """本地 OCR 处理一本书（复用 batch_ingest 的 dispatch 逻辑）"""
        # 动态导入，在笔记本未必有完整项目目录也能工作
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from batch_ingest import _process_one_book
        status = book.get("status", "")
        book_id = book.get("book_id", "")
        artifact_id = book.get("artifact_id", "")
        result = _process_one_book(
            pdf_path, book_id, artifact_id, status, record=book,
            dpi=200, poppler_path=None, max_pages=None,
        )
        return result

    def post_evidence(self, result: dict):
        """把 OCR 结果 POST 回主机 shard evidence"""
        book_id = result.get("book_id", "")
        artifact_id = result.get("artifact_id", "")
        meta = result.get("metadata", {})
        # 简单起见每本书 POST 一页一页传太慢，改为 POST 整本书的 pages JSONL 文本
        # 按 pages.jsonl 格式拼
        pages_lines = []
        for p in result.get("pages", []):
            pa = {
                "book_id": book_id,
                "artifact_id": artifact_id,
                "page_index": p["page_index"],
                "text_raw": p.get("text_raw", ""),
                "text_normalized": p.get("text_normalized", ""),
                "confidence": p.get("confidence", 1.0),
                "block_count": p.get("block_count", 0),
                "extractor": p.get("extractor", "unknown"),
                "extractor_version": p.get("extractor_version", "unknown"),
                "normalization_version": p.get("normalization_version", "norm_v1"),
                "evidence_set_id": "",
            }
            pages_lines.append(json.dumps(pa, ensure_ascii=False))
        body = ("\n".join(pages_lines) + "\n").encode("utf-8")
        path = f"/api/shard{self.shard}/pages"
        self._post(path, body)

    def post_checkpoint(self, entry: dict):
        body = (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8")
        self._post(f"/api/shard{self.shard}/checkpoint", body)

    def run(self, limit: int | None = None):
        print(f"[worker] Shard {self.shard}: fetching manifest...", file=sys.stderr)
        books = self.fetch_manifest()
        if limit:
            books = books[:limit]
        print(f"[worker] Shard {self.shard}: {len(books)} books total", file=sys.stderr)

        # 加载已有 checkpoint
        done_keys = set()
        cp_path = Path.home() / f"ocr_shard{self.shard}_checkpoint.jsonl"
        if cp_path.exists():
            for line in open(cp_path, encoding="utf-8"):
                try:
                    r = json.loads(line.strip())
                    if r.get("status") == "success":
                        done_keys.add((r.get("book_id", ""), r.get("", "")))
                except Exception:
                    pass

        start = time.time()
        for i, book in enumerate(books):
            book_id = book.get("book_id", "?")
            elapsed = time.time() - start
            avg = elapsed / max(1, self.stats["success"] + self.stats["error"])
            remaining = avg * (len(books) - i)
            print(f"[{i+1}/{len(books)}] {book_id} ({book.get('status','')}) ETA {remaining/60:.0f}min",
                  file=sys.stderr, flush=True)

            # 跳过 checkpoint
            if book_id in [k[0] for k in done_keys]:
                self.stats["skip"] += 1
                continue

            try:
                pdf_path = self.download_pdf(book)
                if not pdf_path:
                    raise FileNotFoundError(f"PDF not found: {book.get('source_full_path')}")

                result = self.ocr_one_book(pdf_path, book)
                # 写结果回主机
                self.post_evidence(result)
                self.post_checkpoint({
                    "book_id": book_id,
                    "status": "success",
                    "pages": len(result.get("pages", [])),
                    "timestamp": now_iso(),
                })
                # 本地备份 checkpoint
                with open(cp_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"book_id": book_id, "status": "success",
                                         "pages": len(result.get("pages", [])),
                                         "timestamp": now_iso()}, ensure_ascii=False) + "\n")
                self.stats["success"] += 1
                # 清理 PDF 缓存
                try: os.unlink(pdf_path)
                except Exception: pass
            except Exception as e:
                print(f"  ERROR: {e}", file=sys.stderr)
                self.stats["error"] += 1
                self.post_checkpoint({
                    "book_id": book_id, "status": "error",
                    "error": str(e)[:200], "timestamp": now_iso(),
                })

        print(f"\n[worker] Shard {self.shard} done: {self.stats}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shard", type=int, required=True, help="3 or 4")
    parser.add_argument("--host", default="192.168.1.171", help="Host IP")
    parser.add_argument("--port", type=int, default=8899, help="Host HTTP port")
    parser.add_argument("--limit", type=int, default=None, help="Cap books for testing")
    args = parser.parse_args()
    if args.shard not in (3, 4):
        print("--shard must be 3 or 4", file=sys.stderr)
        sys.exit(1)
    worker = HttpWorker(args.host, args.port, args.shard)
    worker.run(limit=args.limit)


if __name__ == "__main__":
    main()
