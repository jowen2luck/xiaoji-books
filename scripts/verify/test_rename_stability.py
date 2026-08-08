"""M1-4: Rename stability test — source_path change must NOT change book_id."""
import json
import shutil
import sys
from pathlib import Path

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.pipeline.ingest import load_manifest, lookup_book_id

MANIFEST_PATH = "data/manifest.jsonl"
TEST_FILE = r"data\_kage\www.marxists.org\chinese\bukharin\053103.pdf"

# Step 1: Load manifest and get current book_id
manifest = load_manifest(MANIFEST_PATH)
book_id_before = lookup_book_id(manifest, TEST_FILE)
artifact_id_before = manifest.get(TEST_FILE, {}).get("artifact_id", "")
print(f"Original: path={TEST_FILE}")
print(f"          book_id={book_id_before}")
print(f"          artifact_id={artifact_id_before}")

# Step 2: Save original manifest entry, modify source_path and source_full_path
MANIFEST_BACKUP = "data/manifest.jsonl.bak"
shutil.copy2(MANIFEST_PATH, MANIFEST_BACKUP)

original_records = []
target_idx = -1
with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
    for i, line in enumerate(f):
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        original_records.append(rec)
        if rec.get("source_path") == TEST_FILE or rec.get("source_full_path") == TEST_FILE:
            target_idx = i

if target_idx < 0:
    print("ERROR: test file not found in manifest!")
    exit(1)

# Modify the entry's paths to simulate a rename
NEW_PATH = r"data\renamed\bukharin\ABC-053103-renamed.pdf"
original_records[target_idx]["source_path"] = NEW_PATH
original_records[target_idx]["source_full_path"] = NEW_PATH
# NOTE: book_id is NOT changed — this is the test

# Write modified manifest
with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
    for rec in original_records:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

# Step 3: Reload and look up by NEW path
manifest2 = load_manifest(MANIFEST_PATH)
book_id_after = lookup_book_id(manifest2, NEW_PATH)
print(f"\nAfter rename: path={NEW_PATH}")
print(f"             book_id={book_id_after}")

# Step 4: Verify
print(f"\nResult: book_id stable = {book_id_before == book_id_after}")
assert book_id_before == book_id_after, "FAIL: book_id changed after rename!"
print("PASS: M1-4 rename stability verified")

# Step 5: Restore original manifest
shutil.copy2(MANIFEST_BACKUP, MANIFEST_PATH)
import os
os.remove(MANIFEST_BACKUP)
print("\nManifest restored to original.")
