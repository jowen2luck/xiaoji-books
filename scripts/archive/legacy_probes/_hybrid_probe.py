import sqlite3, sys
db, q = sys.argv[1], sys.argv[2]
con = sqlite3.connect(db)
rows = con.execute(
    """SELECT book_id, page_index, snippet(pages_fts, -1, '[', ']', '...', 10) AS snip
       FROM pages_fts WHERE text_normalized MATCH ? LIMIT 10""",
    (q,)).fetchall()
print(f"FTS5 results for: {q}")
for i, r in enumerate(rows):
    print(f"  [{i+1}] {r[0]} p{r[1]}: {r[2]}")
