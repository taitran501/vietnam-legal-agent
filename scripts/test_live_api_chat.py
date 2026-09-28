"""Test live chat SSE API stream as a real normal user."""

import json
import urllib.request
import sys


def test_chat_turn(query: str, conversation_id: str, turn_label: str):
    print(f"\n{'='*70}")
    print(f"👉 USER QUERY: {query} ({turn_label})")
    print(f"{'='*70}")

    payload = {
        "query": query,
        "conversation_id": conversation_id,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1/chat",
        data=data,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
    )

    events = []
    collected_answer = []
    has_form = False
    question_form_data = None
    citations = []

    sys.stdout.reconfigure(line_buffering=True)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            for line in resp:
                line_str = line.decode("utf-8").strip()
                if line_str.startswith("data:"):
                    raw_data = line_str[5:].strip()
                    if raw_data:
                        try:
                            ev = json.loads(raw_data)
                            events.append(ev)
                            ev_type = ev.get("type") or ev.get("event")
                            if ev_type == "status":
                                print(f"  [STATUS]: {ev.get('status') or ev.get('message')}")
                            elif ev_type == "response_chunk":
                                chunk = ev.get("chunk") or ev.get("content") or ""
                                collected_answer.append(chunk)
                                sys.stdout.write(chunk)
                                sys.stdout.flush()
                            elif ev_type == "case_update":
                                form = ev.get("question_form")
                                if form:
                                    has_form = True
                                    question_form_data = form
                                    print(f"\n  📋 [QUESTION_FORM RECEIVED]: title='{form.get('title')}', allow_skip={form.get('allow_skip')}, questions={len(form.get('questions', []))}")
                            elif ev_type in ("response_complete", "complete"):
                                citations = ev.get("citations") or []
                                form = ev.get("question_form")
                                if form:
                                    has_form = True
                                    question_form_data = form
                                print(f"\n  ✅ [COMPLETE] - Citations count: {len(citations)}")
                        except json.JSONDecodeError:
                            pass
    except Exception as e:
        print(f"\n❌ Error during SSE stream: {e}")
        return False

    print("\n" + "-"*70)
    print(f"Summary for '{turn_label}':")
    print(f"- Total SSE Events received: {len(events)}")
    print(f"- Final answer length: {sum(len(c) for c in collected_answer)} chars")
    print(f"- Interactive Question Form attached: {has_form}")
    if has_form and question_form_data:
        print(f"  * Form ID: {question_form_data.get('id')}")
        print(f"  * Allow Skip: {question_form_data.get('allow_skip')}")
        print(f"  * Submit Label: {question_form_data.get('submit_label')}")
        print(f"  * Skip Label: {question_form_data.get('skip_label')}")
    print(f"- Citations returned: {len(citations)}")
    return True


if __name__ == "__main__":
    print("🚀 STARTING REAL USER SIMULATION CHAT ON BACKEND & FRONTEND PROXY...")

    # Test 1: Casual question asking about labor contract termination without notice
    test_chat_turn(
        query="em chao anh chi, em moi bi giam doc cho nghi viec ma khong bao truoc gi ca, bao la nghi luon tu ngay mai thi em co duoc den bu gi khong a",
        conversation_id="live-user-conv-labor-01",
        turn_label="Turn 1: Sa thải không báo trước (Không dấu)",
    )

    # Test 2: Legal calculation inquiry
    test_chat_turn(
        query="luong em 15 trieu mot thang, lam viec duoc 2 nam roi, tinh giup em tong tien den bu it nhat la bao nhieu",
        conversation_id="live-user-conv-labor-01",
        turn_label="Turn 2: Yêu cầu tính tiền bồi thường cụ thể",
    )

    # Test 3: Civil lease dispute
    test_chat_turn(
        query="chu nha tu y tang gia thue nha giua chung ma trong hop dong khong co ghi thi co dung luat khong",
        conversation_id="live-user-conv-civil-02",
        turn_label="Turn 3: Tranh chấp tăng giá thuê nhà (Dân sự)",
    )
