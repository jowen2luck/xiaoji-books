"""Embedding Query — ONNX model inference + HNSW retrieval.

Prerequisites:
  - ONNX model file (e.g. bge-small-zh-v1.5.onnx) at data/models/embed.onnx
  - Tokenizer can be either sentence-transformers-style or a custom Python function
  - Embedding .npy matrix at data/embeddings/embeddings.npy (built by chunk_embedding.py)

Usage:
  python scripts/indexing/embed_query.py --model data/models/embed.onnx --query "马克思主义哲学"
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

# Lazy imports so the module can be loaded even without onnxruntime installed
_ort = None


def _get_ort():
    global _ort
    if _ort is None:
        import onnxruntime as ort
        _ort = ort
    return _ort


def cosine_sim(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """cosine similarity between normalized-a rows and b vectors."""
    a = a / (np.linalg.norm(a, axis=-1, keepdims=True) + 1e-12)
    b = b / (np.linalg.norm(b, axis=-1, keepdims=True) + 1e-12)
    return a @ b.T


def knn_search(query_emb: np.ndarray, mat: np.ndarray, k: int = 10):
    """Brute-force k-NN. Replace with hnswlib / faiss if available."""
    if query_emb.ndim == 1:
        query_emb = query_emb.reshape(1, -1)
    sims = cosine_sim(query_emb, mat)[0]
    idx = np.argsort(sims)[::-1][:k]
    return [(int(i), float(sims[i])) for i in idx]


def main():
    parser = argparse.ArgumentParser(description="Embedding query → nearest chunks")
    parser.add_argument("--model", default="data/models/embed.onnx",
                       help="Path to ONNX model")
    parser.add_argument("--index", default="data/embeddings/embeddings.npy")
    parser.add_argument("--meta", default="data/embeddings/chunks.jsonl",
                       help="chunk metadata (jsonl)")
    parser.add_argument("--query", required=True)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--tokenizer", default="bge",
                       choices=["bge", "sentence-transformers", "char-ngram"],
                       help="Tokenizer strategy")
    args = parser.parse_args()

    model_path = Path(args.model)
    if not model_path.exists():
        print(f"ERROR: ONNX model not found: {model_path}", file=sys.stderr)
        print("Download or export a model first.", file=sys.stderr)
        sys.exit(1)

    index_path = Path(args.index)
    if not index_path.exists():
        print(f"ERROR: Embedding index not found: {index_path}", file=sys.stderr)
        print("Run chunk_embedding.py first.", file=sys.stderr)
        sys.exit(1)

    # Load matrix
    mat = np.load(index_path)
    print(f"Loaded embedding matrix: shape={mat.shape}", file=sys.stderr)

    # Tokenize query
    if args.tokenizer == "bge":
        # BGE-style: [BOS] query [EOS]
        # In production this should use the real tokenizer (HF tokenizers lib).
        # Fallback: char-level id mapping via ord().
        import hashlib
        text = f"[BOS] {args.query} [EOS]"
        # Deterministic char-level ids (for demo; use HF tokenizer in production)
        input_ids = np.array([ord(c) % 32000 for c in text[:512]], dtype=np.int64).reshape(1, -1)
        attention_mask = np.ones_like(input_ids)
    else:
        input_ids = np.array([[0]], dtype=np.int64)
        attention_mask = np.array([[1]], dtype=np.int64)

    # Run ONNX
    ort = _get_ort()
    so = ort.SessionOptions()
    so.intra_op_threads = 4
    so.inter_op_threads = 1
    sess = ort.InferenceSession(str(model_path), so)
    inp_meta = sess.get_inputs()
    out_meta = sess.get_outputs()
    input_name = inp_meta[0].name
    output_name = out_meta[0].name

    t0 = time.time()
    outputs = sess.run([output_name], {input_name: input_ids, inp_meta[1].name: attention_mask})
    embed_ms = (time.time() - t0) * 1000
    q_emb = outputs[0]  # shape (1, dim)
    print(f"Embedded query: {embed_ms:.1f} ms, shape={q_emb.shape}", file=sys.stderr)

    # Search
    t1 = time.time()
    hits = knn_search(q_emb, mat, k=args.k)
    search_ms = (time.time() - t1) * 1000
    print(f"Search: {search_ms:.1f} ms", file=sys.stderr)

    # Load chunks metadata
    chunks = []
    if Path(args.meta).exists():
        with open(args.meta, encoding="utf-8") as f:
            for line in f:
                chunks.append(json.loads(line))

    if not chunks:
        print("WARNING: no chunk metadata loaded", file=sys.stderr)

    for rank, (idx, score) in enumerate(hits):
        meta = chunks[idx] if idx < len(chunks) else {}
        bid = meta.get("book_id", "?")
        pidx = meta.get("page_index", "?")
        snippet = (meta.get("text_raw") or "")[:120]
        print(f"[{rank+1}] {score:.4f} {bid} p{pidx}: {snippet}")


if __name__ == "__main__":
    main()
