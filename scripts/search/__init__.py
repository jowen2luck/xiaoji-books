"""Hybrid Search module (M5).

Combines:
- FTS5 keyword search (substring via trigram tokenizer)
- Vector similarity search (FAISS)
- RRF (Reciprocal Rank Fusion) for merging
- Concept match (keyword entity aliases)

Returns top-K paragraphs with full Evidence anchors.
Never returns "conclusions" — only facts with provenance (Engine Never Concludes).
"""
