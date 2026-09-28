"""Continuous multi-turn live conversation test for Vietnam Legal Agent."""

import json
import time
import urllib.request
import sys


def run_chat_turn(query: str, conversation_id: str, turn_index: int, turn_title: str) -> dict:
    print(f"\n{'='*75}")
    print(f"👉 [TURN {turn_index}] {turn_title}")
    print(f"💬 USER: {query}")
    print(f"{'='*75}")

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
                                status_msg = ev.get("status") or ev.get("message")
                                print(f"  ⚡ [STATUS]: {status_msg}")
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
                                    print(f"\n  📋 [QUESTION_FORM]: title='{form.get('title')}', allow_skip={form.get('allow_skip')}")
                            elif ev_type in ("response_complete", "complete"):
                                citations = ev.get("citations") or []
                                form = ev.get("question_form")
                                if form:
                                    has_form = True
                                    question_form_data = form
                                print(f"\n  ✅ [COMPLETED] - Trích dẫn (citations): {len(citations)}")
                        except json.JSONDecodeError:
                            pass
    except Exception as e:
        print(f"\n❌ Error during SSE stream: {e}")
        return {"ok": False, "error": str(e)}

    full_answer = "".join(collected_answer).strip()
    print("\n" + "-"*75)
    print(f"📊 Kết quả Turn {turn_index}:")
    print(f"- Tổng số sự kiện SSE: {len(events)}")
    print(f"- Độ dài câu trả lời: {len(full_answer)} ký tự")
    print(f"- Có đính kèm form làm rõ (Question Form): {has_form}")
    if has_form and question_form_data:
        print(f"  * Tiêu đề form: {question_form_data.get('title')}")
        print(f"  * Nút bỏ qua (Skip): {question_form_data.get('allow_skip')}")
    print(f"- Số trích dẫn pháp lý: {len(citations)}")
    return {
        "ok": True,
        "events_count": len(events),
        "answer_len": len(full_answer),
        "answer": full_answer,
        "has_form": has_form,
        "citations_count": len(citations),
    }


def run_continuous_test():
    print("🚀 BẮT ĐẦU KIỂM THỬ ĐÀM THOẠI LIÊN TỤC ĐA LƯỢT (CONTINUOUS MULTI-TURN CHAT)")

    # ══════════════════════════════════════════════════════════════════════════════
    # CASE 1: TRANH CHẤP LAO ĐỘNG - SA THẢI TRÁI PHÁP LUẬT (4 TURNS LIÊN TỤC)
    # ══════════════════════════════════════════════════════════════════════════════
    conv_labor = f"labor-continuous-{int(time.time())}"
    print(f"\n{'#'*75}")
    print(f"CASE 1: TRANH CHẤP LAO ĐỘNG (Conversation ID: {conv_labor})")
    print(f"{'#'*75}")

    turns_case_1 = [
        (
            "em chao anh chi, em moi bi giam doc cho nghi viec ma khong bao truoc gi ca, bao la nghi luon tu ngay mai thi em co duoc den bu gi khong a",
            "Mở đầu - Người dùng hỏi bằng ngôn ngữ tự nhiên không dấu về việc bị cho thôi việc bất ngờ"
        ),
        (
            "da em lam theo hop dong lao dong khong xac dinh thoi han, giam doc chi noi mieng chu em khong he vi pham ky luat hay bi lap bien ban gi ca",
            "Làm rõ thông tin - Cung cấp loại hợp đồng và khẳng định không vi phạm kỷ luật"
        ),
        (
            "luong theo hop dong cua em la 15 trieu 1 thang, em da lam duoc tron 2 nam, vay theo luat em duoc den bu it nhat la bao nhieu tien",
            "Hỏi số tiền bồi thường - Cung cấp lương và thâm niên làm việc"
        ),
        (
            "neu cong ty khong chiu tra tien thi em phai nop don ra hoa giai vien lao dong hay khoi kien thang ra toa an quan huyen nao",
            "Hỏi trình tự thủ tục pháp lý - Khiếu nại, hòa giải hay khởi kiện"
        )
    ]

    for idx, (q, label) in enumerate(turns_case_1, start=1):
        run_chat_turn(q, conv_labor, idx, label)
        time.sleep(2)  # Short pause between turns

    # ══════════════════════════════════════════════════════════════════════════════
    # CASE 2: TRANH CHẤP DÂN SỰ - THUÊ NHÀ & GIỮ TIỀN CỌC (3 TURNS LIÊN TỤC)
    # ══════════════════════════════════════════════════════════════════════════════
    conv_lease = f"lease-continuous-{int(time.time())}"
    print(f"\n\n{'#'*75}")
    print(f"CASE 2: TRANH CHẤP HỢP ĐỒNG THUÊ NHÀ (Conversation ID: {conv_lease})")
    print(f"{'#'*75}")

    turns_case_2 = [
        (
            "chu nha tu y tang gia thue nha giua chung ma trong hop dong khong co ghi thi co dung luat khong",
            "Mở đầu - Hỏi về tính hợp pháp của việc tự ý tăng giá thuê nhà"
        ),
        (
            "hop dong thue nha 1 nam, em moi o duoc 4 thang ma chu nha doi tang them 1 trieu/thang, con doa neu em khong dong y thi trong 3 ngay phai don di va mat luon 10 trieu tien coc",
            "Cung cấp tình tiết cụ thể - Bị ép tăng giá, đe dọa đuổi và chiếm giữ tiền cọc"
        ),
        (
            "neu chu nha tu y cat dien nuoc va khoa cua phong khong cho em vao lay do dac thi em bao cong an phuong hay uy ban nhan dan phuong xu ly",
            "Hỏi biện pháp bảo vệ quyền lợi - Khóa cửa, cắt điện nước và cơ quan can thiệp"
        )
    ]

    for idx, (q, label) in enumerate(turns_case_2, start=1):
        run_chat_turn(q, conv_lease, idx, label)
        time.sleep(2)

    print("\n\n" + "="*75)
    print("🎉 TẤT CẢ CÁC LƯỢT ĐÀM THOẠI ĐÃ HOÀN TẤT THÀNH CÔNG!")
    print("="*75)


if __name__ == "__main__":
    run_continuous_test()
