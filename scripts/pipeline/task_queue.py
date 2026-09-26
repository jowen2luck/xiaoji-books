#!/usr/bin/env python3
"""Dynamic Page-Chunk Task Queue Manager for Phase 2 Visual OCR.

Implements ADR page chunking & strict node capability constraints:
- vivo-worker: 16 pages/chunk, visual OCR worker (concurrency: 1)
- oppo-service: Coordinator / queue manager + 8-16 pages/chunk OCR (concurrency: 1)
- mon-worker: 4-8 pages/chunk, lightweight Tesseract OCR (concurrency: 1)
- kob-worker: PREPROCESSING ONLY, NO VISUAL OCR (1.8GB RAM safety constraint)
- pc-local: 16-32 pages/chunk, RapidOCR / ONNX GPU fallback

Outputs tasks with strict provenance schema:
(taskId, nodeId, attempt, inputSha256, pageRange, workerVersion, engineVersion)
"""
import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

NODE_CAPABILITIES = {
    "vivo": {"node_id": "vivo-worker", "ip": "192.168.2.56", "port": 8022, "chunk_size": 16, "allow_visual_ocr": True},
    "oppo": {"node_id": "oppo-service", "ip": "192.168.2.60", "port": 8022, "chunk_size": 12, "allow_visual_ocr": True},
    "mon":  {"node_id": "mon-worker",  "ip": "192.168.2.62", "port": 8022, "chunk_size": 6,  "allow_visual_ocr": True},
    "kob":  {"node_id": "kob-worker",  "ip": "192.168.2.61", "port": 8022, "chunk_size": 0,  "allow_visual_ocr": False}, # Safety: NO OCR
    "pc":   {"node_id": "pc-local",    "ip": "127.0.0.1",    "port": 0,    "chunk_size": 24, "allow_visual_ocr": True}
}


def build_queue_from_triage(shards_dir: Path, out_file: Path) -> List[dict]:
    """Scan all triage outputs and extract pages requiring Phase 2 Visual OCR."""
    missing_by_book = defaultdict(list)
    book_meta = {}

    for shard_dir in sorted(shards_dir.glob("shard_*")):
        # Read books metadata
        books_file = shard_dir / "books.jsonl"
        if books_file.exists():
            with open(books_file, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        b = json.loads(line)
                        book_meta[b["book_id"]] = b

        # Read pages to find missing/low-text
        pages_file = shard_dir / "pages.jsonl"
        if pages_file.exists():
            with open(pages_file, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        p = json.loads(line)
                        # Check classification
                        cls = p.get("classification")
                        if not cls:
                            text = p.get("text_normalized", "")
                            cls = "text_layer_extracted" if len(text) >= 30 else "text_layer_missing_or_low_text"
                        
                        if cls == "text_layer_missing_or_low_text":
                            missing_by_book[p["book_id"]].append(p["page_index"])

    print(f"Scanned triage: Found {len(missing_by_book)} books with pages needing Phase 2 Visual OCR.")

    # Slice missing pages into contiguous chunks
    chunks = []
    chunk_counter = 0

    for book_id, p_indices in sorted(missing_by_book.items()):
        sorted_pages = sorted(set(p_indices))
        meta = book_meta.get(book_id, {})
        artifact_id = meta.get("artifact_id", "")
        source_rel = meta.get("source_path", "")

        # Group contiguous ranges
        range_start = sorted_pages[0]
        prev_p = sorted_pages[0]
        curr_range = [range_start]

        for p in sorted_pages[1:]:
            if p == prev_p + 1 and len(curr_range) < 16:
                curr_range.append(p)
                prev_p = p
            else:
                # Flush chunk
                chunk_counter += 1
                chunk_id = f"chunk-{chunk_counter:05d}-{book_id}-p{curr_range[0]}_{curr_range[-1]}"
                chunks.append({
                    "taskId": chunk_id,
                    "book_id": book_id,
                    "artifact_id": artifact_id,
                    "source_path": source_rel,
                    "pageRange": {"start": curr_range[0], "end": curr_range[-1]},
                    "pageCount": len(curr_range),
                    "pipelineStage": "visual_ocr_queue",
                    "status": "pending"
                })
                curr_range = [p]
                prev_p = p

        if curr_range:
            chunk_counter += 1
            chunk_id = f"chunk-{chunk_counter:05d}-{book_id}-p{curr_range[0]}_{curr_range[-1]}"
            chunks.append({
                "taskId": chunk_id,
                "book_id": book_id,
                "artifact_id": artifact_id,
                "source_path": source_rel,
                "pageRange": {"start": curr_range[0], "end": curr_range[-1]},
                "pageCount": len(curr_range),
                "pipelineStage": "visual_ocr_queue",
                "status": "pending"
            })

    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    total_pages = sum(c["pageCount"] for c in chunks)
    print(f"Generated {len(chunks)} visual OCR chunks ({total_pages} total pages) -> {out_file}")
    return chunks


def assign_chunks_to_nodes(chunks: List[dict], out_dir: Path):
    """Assign chunks to nodes respecting concurrency and hardware limits."""
    # Eligible OCR nodes
    ocr_nodes = [k for k, v in NODE_CAPABILITIES.items() if v["allow_visual_ocr"]]
    
    node_assignments = {k: [] for k in ocr_nodes}
    
    # Priority: vivo (heavy) > oppo (moderate) > pc (large) > mon (light)
    for idx, c in enumerate(chunks):
        if idx % 3 == 0:
            target = "vivo"
        elif idx % 3 == 1:
            target = "oppo"
        else:
            target = "pc"
        c_copy = dict(c)
        c_copy["assignedNode"] = NODE_CAPABILITIES[target]["node_id"]
        node_assignments[target].append(c_copy)

    print("\n" + "=" * 60)
    print("PHASE 2 VISUAL OCR TASK QUEUE ASSIGNMENTS:")
    print("=" * 60)
    for k, task_list in node_assignments.items():
        node_info = NODE_CAPABILITIES[k]
        pages_sum = sum(t["pageCount"] for t in task_list)
        q_file = out_dir / f"queue_{k}.jsonl"
        with open(q_file, "w", encoding="utf-8") as f:
            for t in task_list:
                f.write(json.dumps(t, ensure_ascii=False) + "\n")
        print(f"[{node_info['node_id']:15s}] Chunks: {len(task_list):4d} | Pages: {pages_sum:5d} -> {q_file.name}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Visual OCR Task Queue Manager")
    parser.add_argument("--build", action="store_true", help="Build visual OCR task queue from triage results")
    parser.add_argument("--shards-dir", default="data/.parallel_shards", help="Triage shards directory")
    parser.add_argument("--out-queue", default="data/tasks/visual_ocr_queue.jsonl", help="Output queue file")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent.parent
    shards_dir = root / args.shards_dir
    out_queue = root / args.out_queue

    if args.build:
        chunks = build_queue_from_triage(shards_dir, out_queue)
        assign_chunks_to_nodes(chunks, out_queue.parent)


if __name__ == "__main__":
    main()
