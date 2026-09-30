import json, os

lines = open("data/batch_checkpoint.jsonl", encoding="utf-8").readlines()
js = [json.loads(l) for l in lines if l.strip()]
succ = [j for j in js if j.get("status") == "success"]
err = [j for j in js if j.get("status") == "error"]

print(f"checkpoint rows: {len(js)}")
print(f"  success: {len(succ)}")
print(f"  error: {len(err)}")
books = set(j["book_id"] for j in succ)
print(f"unique book_ids: {len(books)}")
print(f"last 5:")
for j in succ[-5:]:
    print(f"  {j['book_id']} @ {j['timestamp']} pg={j.get('pages')} paras={j.get('paragraphs')}")

total_pages = sum(j.get("pages", 0) for j in succ)
total_paras = sum(j.get("paragraphs", 0) for j in succ)
print(f"total pages: {total_pages}")
print(f"total paragraphs: {total_paras}")

for name in ["books.jsonl", "pages.jsonl", "paragraphs.jsonl"]:
    p = f"data/evidence/{name}"
    if os.path.exists(p):
        sz = os.path.getsize(p)
        with open(p, encoding="utf-8") as f:
            lc = sum(1 for _ in f)
        print(f"evidence {name}: {sz/1024/1024:.1f}MB {lc}lines")
