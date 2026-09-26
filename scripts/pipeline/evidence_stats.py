"""Evidence Stats — profile paragraph lengths and page structure for embedding design."""
import json
import sys
from collections import defaultdict
from pathlib import Path
import statistics


def main():
    ev_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/evidence")
    para_lengths = []
    blocks_per_page = []
    paras_per_page = defaultdict(int)
    books = set()
    dedup_pages = set()

    for d in sorted(ev_dir.iterdir()):
        if not d.is_dir() or not d.name.startswith("shard"):
            continue
        pp = d / "pages.jsonl"
        if pp.exists():
            for line in pp.open(encoding="utf-8"):
                try:
                    r = json.loads(line)
                    key = (r.get("book_id"), r.get("page_index"))
                    if key in dedup_pages:
                        continue
                    dedup_pages.add(key)
                    bp = r.get("block_count", 0)
                    blocks_per_page.append(bp)
                except Exception:
                    pass
        bpp = d / "paragraphs.jsonl"
        if bpp.exists():
            for line in bpp.open(encoding="utf-8"):
                try:
                    r = json.loads(line)
                    bid = r.get("book_id", "?")
                    books.add(bid)
                    pid = r.get("page_id") or f"{bid}:p{r.get('page_index', '?')}"
                    paras_per_page[pid] += 1
                    text = r.get("text_normalized") or r.get("text_raw") or ""
                    para_lengths.append(len(text))
                except Exception:
                    pass

    def pct(lst, p):
        return round(statistics.quantiles(lst, n=100)[p - 1], 1) if lst else 0

    print(f"Books with paragraphs: {len(books)}")
    print(f"Total paragraphs: {len(para_lengths)}")
    print(f"Total unique pages: {len(dedup_pages)}")
    print()
    print("=== Paragraph Length (chars) ===")
    if para_lengths:
        print(f"  min={min(para_lengths)}  max={max(para_lengths)}  mean={pct(para_lengths,50)}")
        print(f"  p25={pct(para_lengths,25)}  p50={pct(para_lengths,50)}  p75={pct(para_lengths,75)}  p95={pct(para_lengths,95)}  p99={pct(para_lengths,99)}")
    print()
    print("=== Pages per Book ===")
    ppg = list(paras_per_page.values())
    if ppg:
        print(f"  paras/page: min={min(ppg)}  max={max(ppg)}  mean={round(statistics.mean(ppg),1)}  median={statistics.median(ppg)}")
    print()
    print("=== Blocks per Page ===")
    if blocks_per_page:
        print(f"  min={min(blocks_per_page)}  max={max(blocks_per_page)}  mean={round(statistics.mean(blocks_per_page),1)}")


if __name__ == "__main__":
    main()
