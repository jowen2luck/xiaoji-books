"""Test manifest loading and book_id lookup for M1-3."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.pipeline.ingest import load_manifest, lookup_book_id

manifest_path = "data/manifest.jsonl"
m = load_manifest(manifest_path)
print(f"Manifest entries: {len(m)}")

# Test 1: known file
test_path = r"data\_kage\www.marxists.org\chinese\bukharin\053103.pdf"
bid = lookup_book_id(m, test_path)
print(f"  {test_path} -> {bid}")

# Test 2: alternative path format (forward slash)
test_path2 = "data/_kage/www.marxists.org/chinese/bukharin/053103.pdf"
bid2 = lookup_book_id(m, test_path2)
print(f"  {test_path2} -> {bid2}")

# Test 3: book_id should be identical regardless of path format
print(f"  Both paths resolve to same book_id: {bid == bid2}")

# Test 4: the lookup shouldn't use filename as key
test_path3 = "data/chinese/bukharin/053103.pdf"  # different path structure
bid3 = lookup_book_id(m, test_path3)
print(f"  {test_path3} -> {bid3} (should be None or same if in manifest)")
