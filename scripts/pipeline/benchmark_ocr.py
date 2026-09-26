"""OCR Quality Benchmark — sample pages, measure quality signals.

Inputs:
  - evidence_dir (contains shard*/ sub-dirs with pages.jsonl + books.jsonl)
  - n_pages: total pages to sample (default 30)
  - seed: random seed

Outputs (JSON):
  - per_page_samples: list of {shard,book_id,page_index,cjk_ratio,block_count,avg_confidence,text_len}
  - per_book_aggregates: {book_id, n_sampled, avg_cjk_ratio, avg_confidence, avg_blocks_per_page}
  - global_summary: {total_sampled, pct_cjk_gt_0_3, pct_confidence_lt_0_7, ...}
  - flagged_low_quality_books: list of book_id with cjk_ratio < 0.1 or confidence < 0.6

Quality heuristics (no 真理值, only internal signals):
  - cjk_ratio: fraction of CJK chars among all non-space chars; low ratio => engine missed text
  - avg_confidence: mean of RapidOCR block confidence (0..1); < 0.7 = degraded scan / small text
  - blocks_per_page: box density; 0 = blank missed; 1 = whole-page bbox (layout collapsed)
"""
import argparse
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path


CJK_RE = re.compile(r"[一-鿿㐀-䶿　-〿＀-￯]")


def cjk_ratio(text: str) -> float:
    if not text:
        return 0.0
    total = sum(1 for c in text if not c.isspace())
    if total == 0:
        return 0.0
    cjk = len(CJK_RE.findall(text))
    return round(cjk / total, 4)


def load_evidence_index(ev_dir: Path) -> list[dict]:
    """Scan shard*/ sub-dirs, load pages.jsonl + books.jsonl."""
    # Returns a list of page records, each tagged with shard name
    all_pages = []
    books_meta = {}
    for d in sorted(ev_dir.iterdir()):
        if not d.is_dir() or not d.name.startswith("shard"):
            continue
        bp = d / "books.jsonl"
        if bp.exists():
            for line in bp.open(encoding="utf-8"):
                try:
                    r = json.loads(line)
                    books_meta[r.get("book_id")] = r
                except Exception:
                    pass
        pp = d / "pages.jsonl"
        if not pp.exists():
            continue
        for line in pp.open(encoding="utf-8"):
            try:
                r = json.loads(line)
                r["_shard"] = d.name
                all_pages.append(r)
            except Exception:
                pass
    return all_pages, books_meta


def main():
    parser = argparse.ArgumentParser(description="OCR quality benchmark")
    parser.add_argument("--evidence-dir", default="data/evidence")
    parser.add_argument("--n-pages", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default="data/benchmark_ocr.json")
    args = parser.parse_args()

    ev_dir = Path(args.evidence_dir)
    all_pages, _ = load_evidence_index(ev_dir)

    if not all_pages:
        print("ERROR: no pages.jsonl found in evidence_dir/shard*/", file=sys.stderr)
        sys.exit(1)

    # Group by book, ensure sample spans multiple books if possible
    by_book = defaultdict(list)
    for p in all_pages:
        by_book[p.get("book_id", "?")].append(p)

    # Sample: pick pages from distinct books up to min(n, n_books); fill remainder with random
    rng = random.Random(args.seed)
    all_book_ids = sorted(by_book.keys())
    samples = []
    # Round-robin across books for diversity
    max_per_book = max(1, args.n_pages // max(1, len(all_book_ids)))
    rng.shuffle(all_book_ids)
    for bid in all_book_ids:
        if len(samples) >= args.n_pages:
            break
        pool = by_book[bid]
        k = min(max_per_book, len(pool), args.n_pages - len(samples))
        samples.extend(rng.sample(pool, k))
    # Top up if still short
    while len(samples) < args.n_pages:
        samples.append(rng.choice(all_pages))

    samples = samples[: args.n_pages]

    # Build per-page quality record
    records = []
    per_book = defaultdict(lambda: {"n": 0, "cjk_sum": 0.0, "conf_sum": 0.0, "blocks_sum": 0, "text_len_sum": 0})
    for p in samples:
        bid = p.get("book_id", "?")
        text = p.get("text_normalized") or p.get("text_raw") or ""
        ratio = cjk_ratio(text)
        blocks = p.get("block_count", 0)
        conf = float(p.get("confidence") or 0.0)
        rec = {
            "shard": p.get("_shard", "?"),
            "book_id": bid,
            "page_index": p.get("page_index", -1),
            "printed_page": p.get("printed_page", "?"),
            "cjk_ratio": ratio,
            "block_count": blocks,
            "avg_confidence": round(conf, 4),
            "text_len": len(text),
            "extractor": p.get("extractor", "?"),
        }
        records.append(rec)
        b = per_book[bid]
        b["n"] += 1
        b["cjk_sum"] += ratio
        b["conf_sum"] += conf
        b["blocks_sum"] += blocks
        b["text_len_sum"] += len(text)

    per_book_agg = {}
    for bid, agg in per_book.items():
        n = agg["n"]
        per_book_agg[bid] = {
            "n_sampled": n,
            "avg_cjk_ratio": round(agg["cjk_sum"] / n, 4),
            "avg_confidence": round(agg["conf_sum"] / n, 4),
            "avg_blocks_per_page": round(agg["blocks_sum"] / n, 2),
            "avg_text_len": round(agg["text_len_sum"] / n, 0),
        }

    # Global summary
    total = len(records)
    pct_cjk_gt_0_3 = round(sum(1 for r in records if r["cjk_ratio"] >= 0.3) / total, 3) if total else 0
    pct_conf_lt_0_7 = round(sum(1 for r in records if r["avg_confidence"] < 0.7) / total, 3) if total else 0
    avg_cjk = round(sum(r["cjk_ratio"] for r in records) / total, 4) if total else 0
    avg_conf = round(sum(r["avg_confidence"] for r in records) / total, 4) if total else 0

    # Flag low-quality books — excluding text_extractable-style entries
    # (those have block_count=0 & confidence=1.0 by design: block_count loses meaning)
    flagged = []
    for bid, agg in per_book_agg.items():
        is_block_zero_conf_one = (agg["avg_blocks_per_page"] == 0 and agg["avg_confidence"] >= 0.999)
        if is_block_zero_conf_one:
            # text_extract pipeline — block_count meaningless; flag only on cjk_ratio
            if agg["avg_cjk_ratio"] < 0.1:
                flagged.append({
                    "book_id": bid,
                    "reason": "low_cjk_text_extract",
                    "avg_cjk_ratio": agg["avg_cjk_ratio"],
                    "avg_confidence": agg["avg_confidence"],
                    "note": "blocks_per_page=0 is normal for pdfplumber text_extract",
                })
        else:
            # RapidOCR pipeline — all three signals meaningful
            reasons = []
            if agg["avg_cjk_ratio"] < 0.05:
                reasons.append("low_cjk")
            if agg["avg_confidence"] < 0.5:
                reasons.append("low_confidence")
            if agg["avg_blocks_per_page"] < 1 and agg["avg_text_len"] > 100:
                reasons.append("layout_collapsed")
            if reasons:
                flagged.append({
                    "book_id": bid,
                    "reason": "+".join(reasons),
                    "avg_cjk_ratio": agg["avg_cjk_ratio"],
                    "avg_confidence": agg["avg_confidence"],
                })

    report = {
        "meta": {
            "evidence_dir": str(ev_dir),
            "total_pages_available": len(all_pages),
            "total_books_available": len(by_book),
            "n_sampled": total,
            "seed": args.seed,
        },
        "per_book_aggregates": per_book_agg,
        "per_page_samples": records,
        "global_summary": {
            "avg_cjk_ratio": avg_cjk,
            "avg_confidence": avg_conf,
            "pct_pages_cjk_ratio_ge_0_3": pct_cjk_gt_0_3,
            "pct_pages_confidence_lt_0_7": pct_conf_lt_0_7,
            "n_flagged_books": len(flagged),
        },
        "flagged_low_quality_books": flagged,
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"Sampled {total} pages from {len(per_book_agg)} books", file=sys.stderr)
    print(f"Global: avg_cjk_ratio={avg_cjk:.3f}  avg_confidence={avg_conf:.3f}", file=sys.stderr)
    print(f"       pct_cjk_ratio>=0.3: {pct_cjk_gt_0_3:.1%}", file=sys.stderr)
    print(f"       pct_confidence<0.7: {pct_conf_lt_0_7:.1%}", file=sys.stderr)
    print(f"Flagged: {len(flagged)} books", file=sys.stderr)


if __name__ == "__main__":
    main()
