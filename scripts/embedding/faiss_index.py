"""FAISS Vector Index (M5).

Builds and queries a FAISS index over semantic chunk embeddings.
Uses IndexIVFFlat or HNSW for approximate search.
Maintains a JSONL mapping file (vectors_map.jsonl) linking FAISS internal IDs
to semantic_chunk_ids.

Usage:
    python scripts/embedding/faiss_index.py --build --chunks data/navigation/semantic_chunks.jsonl --index data/index/vectors.faiss --map data/index/vectors_map.jsonl
    python scripts/embedding/faiss_index.py --query "query text" --index data/index/vectors.faiss --map data/index/vectors_map.jsonl --topk 5
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

# Optional FAISS import
try:
    import faiss
    HAS_FAISS = True
except ImportError:
    HAS_FAISS = False
    print("WARN: faiss not installed. FAISS operations unavailable.", file=sys.stderr)
    print("Install with: pip install faiss-cpu", file=sys.stderr)

# Parent package import
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from model import EmbeddingModel


def build_index(
    chunks_path: str,
    index_path: str,
    map_path: str,
    model_name: str = "mock",
    use_hnsw: bool = False,
):
    """Build FAISS index from semantic chunks JSONL.
    
    Args:
        chunks_path: Path to semantic_chunks.jsonl
        index_path: Output path for FAISS index (.faiss)
        map_path: Output path for vectors_map.jsonl
        model_name: EmbeddingModel name
        use_hnsw: Use HNSW index (more memory, faster) vs IVF (less memory)
    """
    if not HAS_FAISS:
        raise RuntimeError("faiss required for build_index")
    
    if not Path(chunks_path).exists():
        raise FileNotFoundError(f"Chunks file not found: {chunks_path}")
    
    # Load chunks
    chunks = []
    with open(chunks_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(json.loads(line))
    
    if not chunks:
        print("No chunks to index", file=sys.stderr)
        return 0
    
    print(f"Loaded {len(chunks)} chunks", file=sys.stderr)
    
    # Generate embeddings
    model = EmbeddingModel.create(model_name)
    model.load()
    
    texts = [c.get("chunk_text", "") for c in chunks]
    dim = model.dim
    
    batch_size = 64
    all_vectors = []
    
    t0 = time.time()
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        vectors = model.encode(batch)
        all_vectors.extend(vectors)
        if (i + batch_size) % 256 < batch_size:
            print(f"  Embedded {min(i + batch_size, len(texts))}/{len(texts)}", file=sys.stderr, flush=True)
    
    embed_time = time.time() - t0
    print(f"Embeddings done: {len(all_vectors)} vectors in {embed_time:.1f}s "
          f"({embed_time/len(all_vectors)*1000:.1f}ms/vec)", file=sys.stderr)
    
    # Build FAISS index
    import numpy as np
    matrix = np.array(all_vectors, dtype="float32")
    
    n = len(all_vectors)
    
    if use_hnsw:
        # HNSW: fast search, high memory
        index = faiss.IndexHNSWFlat(dim, 32)
        index.hnsw.efConstruction = 40
        index.add(matrix)
    else:
        # IVF: moderate speed, less memory
        # Use sqrt(n) clusters as heuristic
        nlist = max(1, int(n ** 0.5))
        quantizer = faiss.IndexFlatIP(dim)  # inner product (cosine since normalized)
        index = faiss.IndexIVFFlat(quantizer, dim, nlist, faiss.METRIC_INNER_PRODUCT)
        # Train on the data (IVF requires training step)
        if n >= nlist:
            index.train(matrix)
        index.add(matrix)
        index.nprobe = max(1, nlist // 4)  # search 25% of clusters
    
    # Ensure output dir exists
    Path(index_path).parent.mkdir(parents=True, exist_ok=True)
    
    # Write index
    faiss.write_index(index, index_path)
    
    # Write vector → chunk_id mapping
    Path(map_path).parent.mkdir(parents=True, exist_ok=True)
    with open(map_path, "w", encoding="utf-8") as f:
        for i, chunk in enumerate(chunks):
            record = {
                "faiss_id": i,
                "chunk_id": chunk.get("id", f"sc-{i}"),
                "book_id": chunk.get("book_id", ""),
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    
    print(f"Wrote FAISS index: {index_path} ({n} vectors, dim={dim})", file=sys.stderr)
    print(f"Wrote vectors map: {map_path}", file=sys.stderr)
    return n


def search(
    query: str,
    index_path: str,
    map_path: str,
    model_name: str = "mock",
    topk: int = 10,
) -> list:
    """Query the FAISS index.
    
    Returns: list of {"chunk_id", "book_id", "score", "faiss_id"}
    """
    if not HAS_FAISS:
        raise RuntimeError("faiss required for search")
    
    # Load index
    index = faiss.read_index(index_path)
    
    # Load mapping
    mapping = []
    with open(map_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                mapping.append(json.loads(line))
    
    # Embed query
    model = EmbeddingModel.create(model_name)
    query_vec = model.encode([query])
    
    import numpy as np
    q = np.array(query_vec, dtype="float32")
    
    # Search
    scores, ids = index.search(q, topk)
    
    results = []
    for score, fid in zip(scores[0], ids[0]):
        if fid < 0 or fid >= len(mapping):
            continue
        item = mapping[fid]
        results.append({
            "chunk_id": item["chunk_id"],
            "book_id": item.get("book_id", ""),
            "score": float(score),
            "faiss_id": int(fid),
        })
    
    return results


def load_map(map_path: str) -> dict:
    """Load vectors_map.jsonl into a dict keyed by chunk_id."""
    mapping = {}
    with open(map_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            mapping[r["chunk_id"]] = r
    return mapping


def main():
    parser = argparse.ArgumentParser(description="FAISS index management")
    parser.add_argument("--build", action="store_true", help="Build index")
    parser.add_argument("--query", default=None, help="Query text")
    parser.add_argument("--chunks", default="data/navigation/semantic_chunks.jsonl")
    parser.add_argument("--index", default="data/index/vectors.faiss")
    parser.add_argument("--map", default="data/index/vectors_map.jsonl")
    parser.add_argument("--topk", type=int, default=10)
    parser.add_argument("--model", default="mock")
    parser.add_argument("--hnsw", action="store_true")
    args = parser.parse_args()
    
    if args.build:
        n = build_index(args.chunks, args.index, args.map, args.model, args.hnsw)
        print(f"Built index with {n} vectors")
    
    elif args.query:
        results = search(args.query, args.index, args.map, args.model, args.topk)
        for r in results:
            print(f"  {r['chunk_id']} (book={r['book_id']}, score={r['score']:.4f})")
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
