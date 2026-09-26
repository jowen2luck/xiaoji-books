"""Generate skip checkpoint for books already ingested in main evidence dir."""
import json, hashlib, sys
from pathlib import Path
from datetime import datetime, timezone


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    base = Path(sys.argv[1])  # data/evidence
    manifest_path = Path(sys.argv[2])  # data/manifest.jsonl
    out = Path(sys.argv[3])  # checkpoint output

    # Read existing main evidence books.jsonl to get book_id + full source_path + artifact_id
    existing_map = {}  # book_id -> {artifact_id, source_path}
    ebp = base / "books.jsonl"
    if ebp.exists():
        for line in ebp.open(encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            bid = r.get("book_id")
            if bid:
                existing_map[bid] = {
                    "artifact_id": r.get("artifact_id", ""),
                    "source_path": r.get("source_path", ""),
                }

    print(f"Existing in main evidence: {len(existing_map)} books", file=sys.stderr)

    skipped = 0
    with open(out, "w", encoding="utf-8") as f:
        for bid in sorted(existing_map):
            info = existing_map[bid]
            pdf_path = Path(info["source_path"])
            artifact_id = info["artifact_id"]
            if not pdf_path.exists():
                # compute manually
                if pdf_path.exists():
                    artifact_id = f"sha256:{sha256_file(pdf_path)}"
                else:
                    continue
            entry = {
                "book_id": bid,
                "artifact_id": artifact_id,
                "evidence_set_id": "es-skip-existing",
                "extractor_sig": "skip-existing",
                "normalization_version": "norm_v1",
                "status": "skip",
                "pages": 0, "paragraphs": 0, "books_records": 0,
                "text_pages": 0, "ocr_pages": 0, "mixed": False,
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            skipped += 1

    print(f"Wrote {skipped} skip entries to {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
