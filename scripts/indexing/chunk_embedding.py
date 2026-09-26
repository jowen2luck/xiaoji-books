"""Chunk Builder + Embedding Index — M3 layer.

Reads from existing paragraphs.jsonl, chunks at paragraph boundaries
(soft cap 512 chars, hard cap 800 chars with overlap 64),
writes chunks.jsonl + a flat embedding matrix.

Schema (one line in chunks.jsonl / one row in embeddings.npy):
  id          :  chunk-{book_id}-p{page_index}-{chunk_index}-{esid}-{model_short}
  type        :  "chunk"
  book_id     :  from source paragraph
  page_id     :  from source paragraph (book_id:p{page_index}:{esid})
  page_index  :  0-based
  para_ids    :  list of paragraph ids this chunk covers
  char_range  :  [start, end] offset in joined paragraph text
  text_raw    :  actual text to embed
  chunk_index :  0-based within page
  model       :  model name, e.g. "bge-m3"
  model_version: "1.0"
  dim         :  768 (or 1024 depending on model)
  esid        :  evidence_set_id from source
  evidence_version: "ev2"
"""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

CHUNK_SOFT = 512
CHUNK_HARD = 800
CHUNK_OVERLAP = 64


def _chunk_id(book_id, page_index, chunk_index, esid, model_short):
    seed = f"{book_id}:p{page_index}:c{chunk_index}:{esid}:{model_short}"
    h = hashlib.sha256(seed.encode()).hexdigest()[:12]
    return f"chunk-{book_id}-p{page_index}-{chunk_index}-{model_short}-{h}"


def _premerge_short_paragraphs(paragraphs, floor=80):
    """Attach very short paragraphs (< floor chars) to an adjacent longer one.
    Returns list of (merged_para_id, merged_text, covered_para_ids, char_starts).
    Each output item represents one 'logical paragraph' for chunking.
    """
    if not paragraphs:
        return []
    merged = []
    buffer_id, buffer_text, buffer_covered = paragraphs[0][0], paragraphs[0][1], [paragraphs[0][0]]
    for pid, ptext in paragraphs[1:]:
        if len(ptext) < floor:
            # absorb into current buffer
            buffer_text += ptext
            buffer_covered.append(pid)
        else:
            merged.append((buffer_id, buffer_text, buffer_covered))
            buffer_id, buffer_text, buffer_covered = pid, ptext, [pid]
    merged.append((buffer_id, buffer_text, buffer_covered))
    return merged


def _chunk_paragraphs(paragraphs, soft=CHUNK_SOFT, hard=CHUNK_HARD, overlap=CHUNK_OVERLAP):
    """Split joined merged-paragraph text into chunks at paragraph boundaries.

    paragraphs: list of (para_id, text)
    Returns list of (chunk_text, chunk_start, chunk_end, covered_para_ids)
    """
    if not paragraphs:
        return []

    # Pre-merge short paragraphs
    merged = _premerge_short_paragraphs(paragraphs)

    # Build joined text with offsets
    texts = [m[1] for m in merged]
    joined = "".join(texts)
    offsets = []
    cursor = 0
    for m in merged:
        offsets.append((m[0], m[2], cursor, cursor + len(m[1])))
        cursor += len(m[1])

    if len(joined) <= hard:
        # Single chunk for the whole page
        return [(joined, 0, len(joined), [m[0] for m in merged])]

    chunks = []
    pos = 0
    n = len(joined)

    while pos < n:
        remaining = n - pos
        if remaining <= hard:
            # last chunk: take everything
            covered = [oid for oid, _, pstart, pend in offsets if pend > pos]
            chunks.append((joined[pos:], pos, n, covered))
            break

        target = min(pos + soft, n)
        # Find paragraph boundary closest to target
        best_cut = target
        best_dist = float("inf")
        for oid, _, pstart, pend in offsets:
            for cand in (pstart, pend):
                if pos < cand <= min(pos + hard, n):
                    d = abs(cand - target)
                    if d < best_dist:
                        best_dist = d
                        best_cut = cand

        # Absorb small following paragraphs
        for oid, _, pstart, pend in offsets:
            if pstart >= best_cut and pend - best_cut < soft // 2:
                if pend <= pos + hard:
                    best_cut = pend

        covered = [oid for oid, _, pstart, pend in offsets
                   if pend > pos and pstart < best_cut]
        chunks.append((joined[pos:best_cut], pos, best_cut, covered))
        pos = max(best_cut - overlap, pos + 1)

    return chunks


def main():
    parser = __import__("argparse").ArgumentParser(description="Chunk + embed paragraphs")
    parser.add_argument("--evidence-dir", default="data/evidence")
    parser.add_argument("--output-dir", default="data/embeddings")
    parser.add_argument("--model", default="bge-m3",
                       help="Embedding model name (metadata only — actual embedding must run separately)")
    parser.add_argument("--model-version", default="1.0")
    parser.add_argument("--dim", type=int, default=768)
    parser.add_argument("--dry-run", action="store_true", help="Only count chunks, don't write embeddings")
    args = parser.parse_args()

    ev_dir = Path(args.evidence_dir)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    all_chunks = []
    total_paras = 0
    books_seen = set()

    # Gather all paragraphs grouped by page_id
    page_paras = {}  # page_id -> [(para_id, text)]
    for d in sorted(ev_dir.iterdir()):
        if not d.is_dir() or not d.name.startswith("shard"):
            continue
        pf = d / "paragraphs.jsonl"
        if not pf.exists():
            continue
        for line in pf.open(encoding="utf-8"):
            try:
                r = json.loads(line)
            except Exception:
                continue
            pid = r.get("id") or f"{r.get('book_id')}:p{r.get('page_index',0)}:para{r.get('para_index',0)}"
            ptext = r.get("text_normalized") or r.get("text_raw") or ""
            page_id = r.get("page_id") or f"{r.get('book_id')}:p{r.get('page_index',0)}"
            page_paras.setdefault(page_id, []).append((pid, ptext))
            total_paras += 1
            books_seen.add(r.get("book_id"))

    print(f"Evidence: {total_paras} paragraphs across {len(page_paras)} pages from {len(books_seen)} books",
          file=sys.stderr)

    # Chunk each page
    chunks_meta = []
    chunk_texts = []
    for page_id in sorted(page_paras):
        paras = page_paras[page_id]
        # Build (pid, text, char_start) tuples
        cursor = 0
        para_with_offset = []
        pid_to_esid = {}
        book_id = page_id.split(":")[0]
        page_index = int(page_id.split("p")[1].split(":")[0]) if "p" in page_id else 0
        esid = ""
        pid_book = ""

        # Fetch esid from first paragraph of page (via book_id lookup)
        # esid is suffix after last colon in page_id sometimes; let's grab from pid
        if paras:
            ref_pid = paras[0][0]
            # para id format: {book_id}:p{page_index}:para{para_index}:{esid}
            parts = ref_pid.rsplit(":", 1)
            if len(parts) == 2:
                esid = parts[1]

        for pid, ptext in paras:
            para_with_offset.append((pid, ptext))
            cursor += len(ptext)

        chunks = _chunk_paragraphs(para_with_offset)
        for idx, (ctext, cstart, cend, covered_pids) in enumerate(chunks):
            cid = _chunk_id(book_id, page_index, idx, esid[:8], args.model)
            chunks_meta.append({
                "id": cid,
                "type": "chunk",
                "book_id": book_id,
                "page_id": page_id,
                "page_index": page_index,
                "para_ids": covered_pids,
                "char_range": [cstart, cend],
                "text_raw": ctext[:200] + ("..." if len(ctext) > 200 else ""),
                "chunk_index": idx,
                "model": args.model,
                "model_version": args.model_version,
                "dim": args.dim,
                "esid": esid[:8] if esid else "",
                "evidence_version": "ev2",
            })
            chunk_texts.append(ctext)

    print(f"Generated {len(chunks_meta)} chunks", file=sys.stderr)

    if args.dry_run:
        # Stats only
        sizes = [len(t) for t in chunk_texts]
        print(f"Chunk size stats:  min={min(sizes)}  max={max(sizes)}  "
              f"mean={round(sum(sizes)/len(sizes),1)}  median={sorted(sizes)[len(sizes)//2]}")
        # Write preview only
        preview_file = out_dir / "chunks_preview.jsonl"
        with open(preview_file, "w", encoding="utf-8") as f:
            for m in chunks_meta[:20]:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")
        print(f"Wrote preview of 20 chunks to {preview_file}", file=sys.stderr)
    else:
        # Write chunks metadata
        cm_path = out_dir / "chunks.jsonl"
        with open(cm_path, "w", encoding="utf-8") as f:
            for m in chunks_meta:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")
        print(f"Wrote {cm_path} ({len(chunks_meta)} lines)", file=sys.stderr)

        # Write flat embedding matrix (initialized to zeros — fill via embedder)
        shape = (len(chunk_texts), args.dim)
        mat = np.zeros(shape, dtype=np.float32)
        np.save(out_dir / "embeddings.npy", mat)
        print(f"Wrote embeddings.npy shape {shape} (zeros — run embedder to fill)",
              file=sys.stderr)


if __name__ == "__main__":
    main()
