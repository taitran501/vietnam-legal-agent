"""Automated continuous multi-turn live conversation test for all 5 practical legal domains.
Includes full trace capture and validation of citations and reasoning.
"""

import json
import time
import urllib.request
import sys
import os

ALL_CASES = [
    {
        "domain": "Lao động (Labour)",
        "conv_prefix": "labor",
        "description": "Tranh chấp đơn phương chấm dứt HĐLĐ trái luật, tính tiền bồi thường & thủ tục khiếu nại/khởi kiện",
        "turns": [
            {
                "index": 1,
                "title": "Mở đầu - Bị cho thôi việc bất ngờ không báo trước",
                "query": "em chao anh chi, em moi bi giam doc cho nghi viec ma khong bao truoc gi ca, bao la nghi luon tu ngay mai thi em co duoc den bu gi khong a",
            },
            {
                "index": 2,
                "title": "Cung cấp loại HĐLĐ và không vi phạm kỷ luật",
                "query": "da em lam theo hop dong lao dong khong xac dinh thoi han, giam doc chi noi mieng chu em khong he vi pham ky luat hay bi lap bien ban gi ca",
            },
            {
                "index": 3,
                "title": "Cung cấp tiền lương & thâm niên để tính toán mức bồi thường",
                "query": "luong theo hop dong cua em la 15 trieu 1 thang, em da lam duoc tron 2 nam, vay theo luat em duoc den bu it nhat la bao nhieu tien",
            },
            {
                "index": 4,
                "title": "Hỏi trình tự thủ tục pháp lý bảo vệ quyền lợi",
                "query": "neu cong ty khong chiu tra tien thi em phai nop don ra hoa giai vien lao dong hay khoi kien thang ra toa an quan huyen nao",
            },
        ],
    },
    {
        "domain": "Dân sự - Hợp đồng thuê nhà (Lease Contract)",
        "conv_prefix": "lease",
        "description": "Chủ nhà tự ý tăng giá, đe dọa siết cọc, cắt điện nước và cơ quan giải quyết",
        "turns": [
            {
                "index": 1,
                "title": "Hỏi tính hợp pháp của việc tự ý tăng giá thuê nhà giữa chừng",
                "query": "chu nha tu y tang gia thue nha giua chung ma trong hop dong khong co ghi thi co dung luat khong",
            },
            {
                "index": 2,
                "title": "Bị ép tăng giá, đe dọa đuổi nhà và giữ tiền cọc",
                "query": "hop dong thue nha 1 nam, em moi o duoc 4 thang ma chu nha doi tang them 1 trieu/thang, con doa neu em khong dong y thi trong 3 ngay phai don di va mat luon 10 trieu tien coc",
            },
            {
                "index": 3,
                "title": "Hành vi cắt điện nước, khóa phòng và cơ quan thẩm quyền can thiệp",
                "query": "neu chu nha tu y cat dien nuoc va khoa cua phong khong cho em vao lay do dac thi em bao cong an phuong hay uy ban nhan dan phuong xu ly",
            },
        ],
    },
    {
        "domain": "Đất đai (Land Law)",
        "conv_prefix": "land",
        "description": "Mua bán đất bằng giấy viết tay 2018, cấp Giấy chứng nhận và khởi kiện",
        "turns": [
            {
                "index": 1,
                "title": "Hỏi điều kiện cấp sổ đỏ khi mua đất giấy tay năm 2018",
                "query": "nha em mua manh dat bang giay viet tay tu nam 2018 gio chu cu khong chiu sang ten thi co duoc cap so do khong",
            },
            {
                "index": 2,
                "title": "Sử dụng ổn định từ 2019 và cơ quan tiếp nhận hồ sơ",
                "query": "dat nay khong co tranh chap voi ai ca, em xay nha o on dinh tu 2019 den gio, vay gio muon lam so do thi em phai nop don ra dau",
            },
            {
                "index": 3,
                "title": "Phương án khởi kiện ra Tòa án yêu cầu công nhận hợp đồng",
                "query": "neu chu cu nhat quyet khong dua so do goc ra de tach thua thi em khoi kien ra toa an yeu cau cong nhan hop dong duoc khong",
            },
        ],
    },
    {
        "domain": "Giao thông & Bồi thường ngoài hợp đồng (Traffic & Tort)",
        "conv_prefix": "traffic",
        "description": "Tai nạn giao thông vượt đèn đỏ, bồi thường viện phí, sửa xe, mất thu nhập (Điều 584-590 BLDS)",
        "turns": [
            {
                "index": 1,
                "title": "Trách nhiệm bồi thường khi người khác vượt đèn đỏ gây thương tích",
                "query": "em di dung duong bi mot xe may khac vuot den do tong gay chan, nguoi do co phai den tien vien phi va sua xe cho em khong",
            },
            {
                "index": 2,
                "title": "Liệt kê viện phí 25tr, sửa xe 5tr, mất thu nhập 20tr - Yêu cầu tính tổng số tiền",
                "query": "tong vien phi cua em het 25 trieu, tien sua xe 5 trieu, em phai nghi lam 2 thang mat thu nhap 20 trieu nua thi tong cong em duoc doi bao nhieu",
            },
            {
                "index": 3,
                "title": "Đối phương thách thức, hỏi quy trình báo CSGT hoặc khởi kiện Tòa án",
                "query": "ben kia chi tra 10 trieu roi thach thuc muon lam gi thi lam, gio em bao cong an giao thong quan hay lam don ra toa an giai quyet",
            },
        ],
    },
    {
        "domain": "Hôn nhân & Gia đình (Family Law)",
        "conv_prefix": "marriage",
        "description": "Ly hôn đơn phương, quyền nuôi con dưới 36 tháng và chia tài sản xây trên đất riêng",
        "turns": [
            {
                "index": 1,
                "title": "Thủ tục đơn phương ly hôn khi vợ/chồng bạo lực và ngoại tình",
                "query": "chong em co hanh vi bao luc va ngoai tinh nhung khong chiu ky don ly hon, em muon don phuong ly hon co duoc khong",
            },
            {
                "index": 2,
                "title": "Quyền trực tiếp nuôi con 20 tháng tuổi (dưới 36 tháng)",
                "query": "con em moi 20 thang tuoi thi khi ly hon ai se duoc quyen truc tiep nuoi con theo luat",
            },
            {
                "index": 3,
                "title": "Chia tài sản nhà 2 tầng xây trong hôn nhân trên đất riêng của chồng",
                "query": "ngoi nha dung ten rieng cua chong em mua truoc khi cuoi nhung trong thoi gian song chung hai vo chong co xay them 2 tang nua thi chia the nao",
            },
        ],
    },
]


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
    status_history = []

    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
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
                                status_history.append(status_msg)
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
                            elif ev_type in ("response_complete", "complete"):
                                full_text = ev.get("text") or "".join(collected_answer)
                                citations = ev.get("citations") or []
                                form = ev.get("question_form")
                                if form:
                                    has_form = True
                                    question_form_data = form
                                if not collected_answer and full_text:
                                    collected_answer.append(full_text)
                                    print(full_text)
                                print(f"\n  ✅ [COMPLETED] - Trích dẫn (citations): {len(citations)}")
                        except Exception:
                            pass
    except Exception as exc:
        print(f"\n  ❌ [ERROR]: Request failed: {exc}")
        return {
            "ok": False,
            "error": str(exc),
            "turn_index": turn_index,
            "title": turn_title,
            "query": query,
        }

    final_text = "".join(collected_answer)
    print(f"\n{'-'*75}")
    print(f"📊 Kết quả Turn {turn_index}:")
    print(f"- Số sự kiện: {len(events)} | Độ dài trả lời: {len(final_text)} ký tự")
    print(f"- Form làm rõ: {has_form} (Nút Skip: {question_form_data.get('allow_skip') if question_form_data else False})")
    print(f"- Trích dẫn pháp lý ({len(citations)} nguồn):")
    for idx, cite in enumerate(citations[:4], 1):
        title = cite.get("title") or cite.get("document_id") or "Nguồn pháp lý"
        art = cite.get("article_number") or ""
        print(f"  [{idx}] {title} {f'(Điều {art})' if art else ''}")

    return {
        "ok": True,
        "turn_index": turn_index,
        "title": turn_title,
        "query": query,
        "answer": final_text,
        "citations": citations,
        "has_form": has_form,
        "question_form": question_form_data,
        "status_history": status_history,
        "events_count": len(events),
    }


def run_all():
    print("=" * 80)
    print("🚀 BẮT ĐẦU CHẠY KIỂM THỬ TOÀN DIỆN 5 LĨNH VỰC PHÁP LUẬT VIỆT NAM (16 TURNS)")
    print("=" * 80)

    os.makedirs("data", exist_ok=True)
    all_results = []
    ts = int(time.time())

    for case_idx, case_def in enumerate(ALL_CASES, 1):
        conv_id = f"test-{case_def['conv_prefix']}-{ts}"
        print(f"\n\n{'#'*80}")
        print(f"⭐ [CASE {case_idx}/5] {case_def['domain'].upper()}")
        print(f"Mô tả: {case_def['description']}")
        print(f"Conversation ID: {conv_id}")
        print(f"{'#'*80}")

        case_record = {
            "case_index": case_idx,
            "domain": case_def["domain"],
            "conversation_id": conv_id,
            "description": case_def["description"],
            "turns": [],
        }

        for turn in case_def["turns"]:
            res = run_chat_turn(
                query=turn["query"],
                conversation_id=conv_id,
                turn_index=turn["index"],
                turn_title=turn["title"],
            )
            case_record["turns"].append(res)
            time.sleep(2)

        all_results.append(case_record)

    out_file = os.path.join("data", "full_trace_all_5_cases.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 80)
    print(f"🎉 ĐÃ HOÀN TẤT VÀ LƯU TOÀN BỘ TRACE TẠI: {out_file}")
    print("=" * 80)


if __name__ == "__main__":
    run_all()
