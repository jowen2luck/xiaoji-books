"""Quick FTS5 test for CJK substring matching."""
import sqlite3

conn = sqlite3.connect("data/catalog/catalog.db")

print("=== FTS5 Trigram Tests ===")

# Test 1: English term
cur = conn.execute(
    "SELECT book_id, substr(text_normalized, 1, 60) FROM paragraphs_fts "
    "WHERE paragraphs_fts MATCH 'Internationale' LIMIT 3"
)
rows = cur.fetchall()
print(f"\nMATCH 'Internationale': {len(rows)} results")
for r in rows:
    print(f"  {r[0]}: {r[1]}")

# Test 2: Chinese term (bigram should work)
cur = conn.execute(
    "SELECT book_id, substr(text_normalized, 1, 60) FROM paragraphs_fts "
    "WHERE paragraphs_fts MATCH '鲍狄埃' LIMIT 5"
)
rows = cur.fetchall()
print(f"\nMATCH '鲍狄埃': {len(rows)} results")
for r in rows:
    print(f"  {r[0]}: {r[1]}")

# Test 3: Chinese substring (trigram matches 3-char substrings)
cur = conn.execute(
    "SELECT book_id, substr(text_normalized, 1, 60) FROM paragraphs_fts "
    "WHERE paragraphs_fts MATCH '过渡时' LIMIT 5"
)
rows = cur.fetchall()
print(f"\nMATCH '过渡时' (3-char substring): {len(rows)} results")
for r in rows:
    print(f"  {r[0]}: {r[1]}")

# Test 4: still short
cur = conn.execute(
    "SELECT book_id, substr(text_normalized, 1, 60) FROM paragraphs_fts "
    "WHERE paragraphs_fts MATCH '人民文学' LIMIT 5"
)
rows = cur.fetchall()
print(f"\nMATCH '人民文学': {len(rows)} results")
for r in rows:
    print(f"  {r[0]}: {r[1]}")

# Debug: print all FTS content
cur = conn.execute(
    "SELECT book_id, substr(text_normalized, 1, 100) FROM paragraphs_fts"
)
rows = cur.fetchall()
print(f"\n=== All {len(rows)} FTS entries ===")
for r in rows:
    print(f"  {r[0]}: {r[1]}")

conn.close()
