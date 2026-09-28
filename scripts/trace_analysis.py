"""Print executive trace summary of all 5 multi-turn live cases."""
import json

data = json.load(open("data/full_trace_all_5_cases.json", encoding="utf-8"))
print("=" * 80)
print("BÁO CÁO TỔNG HỢP TRACE ĐÀM THOẠI 5 LĨNH VỰC THỰC TẾ (16 LƯỢT HỘI THOẠI)")
print("=" * 80)

for c in data:
    print(f"\n📁 [CASE {c['case_index']}/5] {c['domain'].upper()}")
    print(f"   Mô tả: {c['description']}")
    print(f"   Conversation ID: {c['conversation_id']}")
    for t in c["turns"]:
        cites = [str(x.get("document_id") or x.get("title") or "") for x in t.get("citations", [])]
        print(f"\n   👉 Turn {t['turn_index']}: {t['title']}")
        print(f"      - Query: \"{t['query']}\"")
        print(f"      - Trích dẫn ({len(cites)} nguồn): {cites}")
        print(f"      - Trả lời ({len(t.get('answer', ''))} ký tự):")
        ans_lines = [l.strip() for l in t.get("answer", "").split("\n") if l.strip()]
        for l in ans_lines[:3]:
            print(f"        {l}")
        if len(ans_lines) > 3:
            print("        ...")
