"""Generate skip checkpoint for text_extractable books already in main evidence."""
import hashlib
import json
import sys
from pathlib import Path
from datetime import datetime, timezone


def make_esid(book_id: str, artifact_id: str, extractor_version: str) -> str:
    seed = f"{book_id}:{artifact_id}:{extractor_version}"
    h = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"es-{h}"


def main():
    base = Path(sys.argv[1])  # data/evidence
    out = Path(sys.argv[2])  # checkpoint output
    extractor_version = sys.argv[3]  # e.g. "pdfplumber@0.11.10"
    manifest_path = Path(sys.argv[4]) if len(sys.argv) > 4 else None

    # Get text_extractable book_ids from manifest
    te_ids = set()
    if manifest_path and manifest_path.exists():
        for line in manifest_path.open(encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("status") == "text_extractable":
                te_ids.add(r.get("book_id"))
    print(f"text_extractable book_ids in manifest: {len(te_ids)}", file=sys.stderr)

    # Read existing main evidence books.jsonl (only text_extractable ones)
    existing = {}
    ebp = base / "books.jsonl"
    if ebp.exists():
        for line in ebp.open(encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            bid = r.get("book_id")
            if bid and bid in te_ids:
                existing[bid] = r.get("artifact_id", "")
    print(f"Already ingested & text_extractable: {len(existing)}", file=sys.stderr)

    skipped = 0
    with open(out, "w", encoding="utf-8") as f:
        for bid in sorted(existing):
            aid = existing[bid]
            if not aid.startswith("sha256:"):
                continue
            esid = make_esid(bid, aid, extractor_version)
            entry = {
                "book_id": bid,
                "artifact_id": aid,
                "evidence_set_id": esid,
                "extractor_sig": extractor_version,
                "normalization_version": "norm_v1",
                "status": "success",
                "pages": 0, "paragraphs": 0, "books_records": 0,
                "text_pages": 0, "ocr_pages": 0, "mixed": False,
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            skipped += 1
    print(f"Wrote {skipped} skip entries to {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
