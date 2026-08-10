import json

with open('tests/eval/results_e2e.json', encoding='utf-8') as f:
    results = json.load(f)

print("=== CACHE HIT ROUTING (false negatives) ===")
for r in results:
    if r['source'] == 'cache':
        print(f"  [{r['case_id']}] query={r['query']!r}  actual_route={r['actual_route']!r}")

print()
print("=== KEYWORD MISSES (non-chitchat) ===")
for r in results:
    if r['missing_keywords'] and r['category'] not in ('chitchat',):
        print(f"  [{r['case_id']}] cat={r['category']} source={r['source']}")
        print(f"    Missing: {r['missing_keywords']}")

print()
print("=== QDRANT INDEX WARNING ===")
for r in results:
    if r.get('error') or (r['source'] == 'legal' and r['keyword_hit_rate'] < 0.5):
        print(f"  [{r['case_id']}] source={r['source']} keywords={r['keyword_hit_rate']:.0%}")
