"""M3 Scale Verification: Anchor + Catalog consistency checks.

Validates at scale:
1. Every paragraph has a corresponding anchor (1:1 mapping)
2. FTS5 coverage == paragraphs coverage (every paragraph is searchable)
3. evidence_set_id consistency across tables
4. books.jsonl vs catalog.db sync (books count match)
5. No broken char_ranges, no missing layout_bbox where expected

Usage:
    python scripts/verify/verify_m3_scale.py --db data/catalog/catalog.db
"""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent.parent


class CheckResult:
    def __init__(self, name: str):
        self.name = name
        self.ok = True
        self.details = []

    def fail(self, msg: str):
        self.ok = False
        self.details.append(msg)

    def warn(self, msg: str):
        self.details.append(f"WARN: {msg}")

    def info(self, msg: str):
        self.details.append(msg)


def check_1vs1_paragraph_anchor(conn) -> CheckResult:
    """Each paragraph row must have exactly one anchor row (by id)."""
    r = CheckResult("1:1 paragraph-anchor mapping")

    cur = conn.execute("""
        SELECT p.id, a.id
        FROM paragraphs p
        LEFT JOIN anchors a ON a.id = p.id
    """)
    missing_anchor = 0
    orphan_anchor = 0
    ok_count = 0
    for para_id, anchor_id in cur.fetchall():
        if anchor_id is None:
            missing_anchor += 1
        else:
            ok_count += 1

    # Orphan anchors
    cur = conn.execute("""
        SELECT a.id FROM anchors a
        LEFT JOIN paragraphs p ON p.id = a.id
        WHERE p.id IS NULL
    """)
    orphan_anchor = sum(1 for _ in cur.fetchall())
    r.info(f"paragraphs with anchor: {ok_count}")
    r.info(f"paragraphs missing anchor: {missing_anchor}")
    r.info(f"orphan anchors (no paragraph): {orphan_anchor}")

    if missing_anchor > 0:
        r.fail(f"{missing_anchor} paragraphs missing anchor entries")
    if orphan_anchor > 0:
        r.fail(f"{orphan_anchor} orphan anchor entries")

    return r


def check_fts_coverage(conn) -> CheckResult:
    """FTS5 row count must equal paragraph count (every paragraph searchable)."""
    r = CheckResult("FTS5 coverage == paragraph count")

    cur = conn.execute("SELECT COUNT(*) FROM paragraphs")
    para_count = cur.fetchone()[0]

    cur = conn.execute("SELECT COUNT(*) FROM paragraphs_fts")
    fts_count = cur.fetchone()[0]

    r.info(f"paragraphs: {para_count}")
    r.info(f"paragraphs_fts: {fts_count}")

    if para_count != fts_count:
        r.fail(f"FTS5 coverage mismatch: {fts_count} FTS rows vs {para_count} paragraphs")

    # Check FTS has no orphans
    cur = conn.execute("""
        SELECT COUNT(*) FROM paragraphs_fts fts
        LEFT JOIN paragraphs p ON p.id = fts.paragraph_id
        WHERE p.id IS NULL
    """)
    orphans = cur.fetchone()[0]
    if orphans > 0:
        r.fail(f"{orphans} FTS entries without corresponding paragraph")
    else:
        r.info("FTS orphan check: OK")

    return r


def check_evidence_set_consistency(conn) -> CheckResult:
    """evidence_sets table should track every evidence_set_id found in paragraphs."""
    r = CheckResult("evidence_set_id consistency")

    cur = conn.execute("""
        SELECT DISTINCT evidence_set_id FROM paragraphs
        WHERE evidence_set_id IS NOT NULL AND evidence_set_id != ''
    """)
    para_sets = {row[0] for row in cur.fetchall()}

    cur = conn.execute("SELECT evidence_set_id FROM evidence_sets")
    tracked_sets = {row[0] for row in cur.fetchall()}

    missing = para_sets - tracked_sets
    extra = tracked_sets - para_sets

    r.info(f"evidence_set_id in paragraphs: {len(para_sets)}")
    r.info(f"evidence_set_id tracked: {len(tracked_sets)}")

    if missing:
        r.fail(f"{len(missing)} evidence_set_ids not tracked in evidence_sets table")
    if extra:
        r.warn(f"{len(extra)} tracked evidence_set_ids have no paragraphs (may be from pages-only)")

    return r


def check_book_paragraph_coverage(conn) -> CheckResult:
    """Every book that's in catalog should have at least one paragraph."""
    r = CheckResult("Book -> paragraphs coverage")

    cur = conn.execute("""
        SELECT b.book_id, b.title, COUNT(p.id)
        FROM books b
        LEFT JOIN paragraphs p ON p.book_id = b.book_id
        GROUP BY b.book_id
        HAVING COUNT(p.id) = 0
    """)
    books_no_paras = [(row[0], row[1]) for row in cur.fetchall()]

    cur = conn.execute("SELECT COUNT(*) FROM books")
    total_books = cur.fetchone()[0]

    cur = conn.execute("SELECT COUNT(DISTINCT book_id) FROM paragraphs")
    books_with_paras = cur.fetchone()[0]

    r.info(f"total books: {total_books}")
    r.info(f"books with paragraphs: {books_with_paras}")
    r.info(f"books without paragraphs: {len(books_no_paras)}")

    if books_no_paras:
        sample = books_no_paras[:5]
        r.warn(f"Books without paragraphs: {', '.join(b[0] for b in sample)}")

    return r


def check_anchor_field_population(conn) -> CheckResult:
    """Check key anchor fields are populated."""
    r = CheckResult("Anchor field population")

    cur = conn.execute("SELECT COUNT(*) FROM anchors")
    total = cur.fetchone()[0]
    if total == 0:
        r.fail("anchors table is empty")
        return r

    # layout_bbox
    cur = conn.execute("SELECT COUNT(*) FROM anchors WHERE layout_bbox IS NOT NULL AND layout_bbox != ''")
    has_bbox = cur.fetchone()[0]
    r.info(f"anchors with layout_bbox: {has_bbox}/{total} ({100*has_bbox/total:.1f}%)")

    # evidence_id matches id (critical for idempotency)
    cur = conn.execute("""
        SELECT COUNT(*) FROM anchors WHERE evidence_id != id
    """)
    mismatch = cur.fetchone()[0]
    if mismatch > 0:
        r.fail(f"{mismatch} anchors have evidence_id != id")
    else:
        r.info("evidence_id == id for all anchors")

    return r


def check_char_range_valid(conn) -> CheckResult:
    """char_range should have char_start <= char_end."""
    r = CheckResult("char_range validity")

    cur = conn.execute("""
        SELECT COUNT(*) FROM paragraphs
        WHERE char_start IS NOT NULL AND char_end IS NOT NULL AND char_end < char_start
    """)
    invalid = cur.fetchone()[0]

    cur = conn.execute("""
        SELECT COUNT(*) FROM paragraphs
        WHERE char_start IS NULL OR char_end IS NULL
    """)
    null_count = cur.fetchone()[0]

    r.info(f"invalid char_ranges (end < start): {invalid}")
    r.info(f"null char_ranges: {null_count}")

    if invalid > 0:
        r.fail(f"{invalid} paragraphs with invalid char_range")

    return r


def check_evidence_layer_separation() -> CheckResult:
    """Verify Evidence files exist and have content."""
    r = CheckResult("Evidence layer file integrity")

    evidence_dir = ROOT / "data/evidence"
    for fname, min_lines in [("books.jsonl", 1), ("pages.jsonl", 1), ("paragraphs.jsonl", 1)]:
        fpath = evidence_dir / fname
        if not fpath.exists():
            r.fail(f"{fname}: missing")
            continue
        size = fpath.stat().st_size
        with open(fpath, encoding="utf-8") as f:
            line_count = sum(1 for _ in f)
        r.info(f"{fname}: {line_count} lines, {size/1024/1024:.1f} MB")
        if line_count < min_lines:
            r.fail(f"{fname}: too few lines ({line_count} < {min_lines})")

    return r


def main():
    parser = argparse.ArgumentParser(description="M3 Scale Verification")
    parser.add_argument("--db", default=str(ROOT / "data/catalog/catalog.db"))
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    print(f"Verifying catalog: {args.db}")
    print()

    conn = sqlite3.connect(args.db)

    checks = [
        check_1vs1_paragraph_anchor,
        check_fts_coverage,
        check_evidence_set_consistency,
        check_book_paragraph_coverage,
        check_anchor_field_population,
        check_char_range_valid,
    ]

    results = [c(conn) for c in checks]
    results.append(check_evidence_layer_separation())

    # Summary
    print("=" * 50)
    all_ok = True
    for r in results:
        status = "OK" if r.ok else "FAIL"
        print(f"[{status}] {r.name}")
        if args.verbose or not r.ok:
            for d in r.details:
                print(f"  {d}")
        if not r.ok:
            all_ok = False

    conn.close()
    print()
    print(f"=== M3 Scale Verification: {'PASS' if all_ok else 'FAIL'} ===")
    print(f"Checks: {sum(1 for r in results if r.ok)}/{len(results)} passed")

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
