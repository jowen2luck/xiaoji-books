"""Final verification: ensure skip checkpoint matches batch_ingest formula exactly."""
import hashlib
import json
import sys
from pathlib import Path


def make_esid(book_id, artifact_id, extractor_version):
    seed = f"{book_id}:{artifact_id}:{extractor_version}"
    h = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"es-{h}"


def main():
    cp_file = Path(sys.argv[1])
    extractor_version = sys.argv[2]  # "pdfplumber@0.11.10:norm_v1"
    expected_status = sys.argv[3] if len(sys.argv) > 3 else "success"

    total = 0
    status_mismatch = 0
    esid_mismatch = 0
    ok = 0
    for line in cp_file.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        total += 1
        computed = make_esid(r["book_id"], r["artifact_id"], extractor_version)
        if r.get("evidence_set_id") != computed:
            esid_mismatch += 1
        if r.get("status") != expected_status:
            status_mismatch += 1
        if r.get("evidence_set_id") == computed and r.get("status") == expected_status:
            ok += 1

    print(f"Checkpoint file: {cp_file}")
    print(f"Total entries:   {total}")
    print(f"OK (status + esid match): {ok}")
    print(f"Status mismatch: {status_mismatch}")
    print(f"ESID mismatch:   {esid_mismatch}")
    print(f"Version string:  {extractor_version}")
    return 0 if (ok == total) else 1


if __name__ == "__main__":
    sys.exit(main())
