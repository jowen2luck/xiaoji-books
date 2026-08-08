"""Verify M1 manifest integrity."""

import json
from collections import Counter

# Read manifest
m = []
with open('data/manifest.jsonl') as f:
    for line in f:
        line = line.strip()
        if line:
            m.append(json.loads(line))

print(f'Manifest records: {len(m)}')

# Check unique book_id
ids = [r['book_id'] for r in m]
id_set = set(ids)
print(f'Unique book_id: {len(id_set)}')

# Check collisions
id_counts = Counter(ids)
collisions = {k: v for k, v in id_counts.items() if v > 1}
print(f'Collisions remaining: {len(collisions)}')
if collisions:
    for k, v in list(collisions.items())[:10]:
        print(f'  COLLISION: {k} appears {v} times')

# Check required fields
print('\n=== Required field check ===')
required_fields = ['book_id', 'artifact_id', 'source_path', 'status', 'aliases']
for field in required_fields:
    missing = sum(1 for r in m if not r.get(field))
    print(f'  {field}: {missing} missing')

# Sample duplicate stems
print('\n=== Sample: stem "1" (25 entries) ===')
ones = [r for r in m if r.get('stem') == '1'][:5]
for r in ones:
    art = r['artifact_id'][:25] if r['artifact_id'] else 'EMPTY'
    print(f'  {r["book_id"]:25s} | art={art} | status={r["status"]}')

print('\n=== Sample: stem "4" (22 entries) ===')
fours = [r for r in m if r.get('stem') == '4'][:5]
for r in fours:
    art = r['artifact_id'][:25] if r['artifact_id'] else 'EMPTY'
    print(f'  {r["book_id"]:25s} | art={art} | status={r["status"]}')

# Status distribution
print('\n=== Status distribution ===')
status_counts = Counter(r['status'] for r in m)
for s, c in status_counts.most_common():
    print(f'  {s:20s}: {c:4d}')

# Check artifact_id unique (may have hash collisions theoretically)
print('\n=== Artifact ID uniqueness ===')
arts = [r['artifact_id'] for r in m if r['artifact_id']]
art_set = set(arts)
print(f'  Non-empty artifact_id: {len(arts)}')
print(f'  Unique artifact_id: {len(art_set)}')
art_counts = Counter(arts)
dup_arts = {k: v for k, v in art_counts.items() if v > 1}
print(f'  Duplicate artifact_id (identical file content): {len(dup_arts)}')
if dup_arts:
    for k, v in list(dup_arts.items())[:5]:
        print(f'    {k[:40]}: {v} copies')

print('\n=== M1 Verification Complete ===')
