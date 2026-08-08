"""Full Navigation Rebuild — one-shot regeneration of all M4 assets.

Regenerates:
- derived_catalog (toc_derived table in catalog.db)
- semantic_chunks (data/navigation/semantic_chunks.jsonl)

Safe to run repeatedly. All previous Navigation data is discarded.

Usage:
    python scripts/navigation/full_rebuild.py --db data/catalog/catalog.db
"""
import argparse
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="Full Navigation rebuild")
    parser.add_argument("--db", default="data/catalog/catalog.db")
    args = parser.parse_args()
    
    if not Path(args.db).exists():
        print(f"ERROR: {args.db} does not exist. Run load_catalog.py first.", file=sys.stderr)
        sys.exit(1)
    
    steps = [
        ("derived_catalog", [sys.executable, str(SCRIPT_DIR / "derived_catalog.py"), "--db", args.db]),
        ("semantic_chunks", [sys.executable, str(SCRIPT_DIR / "semantic_chunks.py"), "--db", args.db]),
    ]
    
    for name, cmd in steps:
        print(f"\n=== Step: {name} ===", file=sys.stderr)
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"FAILED: {name}", file=sys.stderr)
            sys.exit(1)
        print(f"OK: {name}", file=sys.stderr)
    
    print("\n=== Navigation rebuild complete ===", file=sys.stderr)


if __name__ == "__main__":
    main()
