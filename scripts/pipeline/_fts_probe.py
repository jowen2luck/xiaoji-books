import sqlite3, sys
db = sys.argv[1]
q = sys.argv[2]
con = sqlite3.connect(db)
con.execute("PRAGMA journal_mode=WAAL")
try:
    rows = con.execute(
        "SELECT book_id, page_index, snippet(pages_fts, -1, '[', ']', '...', 10) FROM pages_fts WHERE text_normalized MATCH ? LIMIT 5",
        (q,)
    ).fetchall()
    for r in rows:
        print(f"  {r[0]} p{r[1]}: {r[2]}")
    print(f"  hits: {len(rows)}")
except Exception as e:
    print(f"  ERROR: {e}")
