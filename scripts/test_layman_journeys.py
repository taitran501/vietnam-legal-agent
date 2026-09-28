"""Simulation of 5 real layman user journeys in Vietnamese (unaccented / slang / multi-turn).

Tests how the Vietnam Legal Agent Harness handles users who know nothing about law,
typing in informal, unaccented Vietnamese, asking complex questions across domains.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

from epr_agent.agent.agent_loop import AgentRunConfig, EprAgentRunner
from epr_agent.agent.tool_registry import get_tool_dependencies
from epr_agent.tools.generation import StaticGenerationGateway
from epr_agent.tools.retrieval import StaticRetrievalGateway

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("layman_simulation")


JOURNEYS = [
    {
        "id": "journey_1_labor",
        "domain": "Lao động & Tiền lương",
        "user_profile": "Người lao động phổ thông, bị sa thải đột ngột trong thời gian thử việc, không được trả lương và bị ép làm thêm Chủ nhật.",
        "turns": [
            {
                "turn": 1,
                "user_query_raw": "alo toi lam o cong ty duoc 2 thang thu viec xong sep bao nghi luon khong tra dong nao voi bat lam them chu nhat khong luong, gio phai lam sao shop",
                "notes": "Không dấu, hoang mang, dùng từ ngữ đời thường ('alo', 'sep', 'shop').",
            },
            {
                "turn": 2,
                "user_query_raw": "luong thu viec cua toi la 10 trieu thang, lam them 2 ngay chu nhat moi ngay 8 tieng thi gio tinh tien the nao de doi cty",
                "notes": "Hỏi cách tính tiền làm thêm giờ Chủ nhật (200%) và quyền lợi lương thử việc (tối thiểu 85%).",
            }
        ]
    },
    {
        "id": "journey_2_land",
        "domain": "Đất đai & Cấp sổ đỏ",
        "user_profile": "Người dân ở quê có mảnh đất khai hoang từ năm 1996 không có giấy tờ, muốn hỏi thủ tục làm sổ đỏ.",
        "turns": [
            {
                "turn": 1,
                "user_query_raw": "nha toi co manh dat khai hoang tu nam 1996 o que gio muon lam so do thi can gi vay ad, co bi thu hoi mat dat khong",
                "notes": "Không dấu, hỏi về cấp Giấy chứng nhận cho đất sử dụng từ năm 1996 (Luật Đất đai 2024 Điều 138).",
            },
            {
                "turn": 2,
                "user_query_raw": "neu lam so do thi co phai dong tien su dung dat nhieu khong va phai nop ho so o dau",
                "notes": "Hỏi tiếp về nghĩa vụ tài chính và thẩm quyền nộp hồ sơ (UBND cấp xã/Văn phòng đăng ký đất đai).",
            }
        ]
    },
    {
        "id": "journey_3_civil_rent",
        "domain": "Thuê nhà & Đặt cọc (Dân sự)",
        "user_profile": "Sinh viên/người đi làm thuê trọ bị chủ nhà tăng giá bất ngờ rồi dọa đuổi và quỵt 5 triệu tiền cọc.",
        "turns": [
            {
                "turn": 1,
                "user_query_raw": "em thue phong tro dat coc 5 trieu hop dong 1 nam moi o duoc 3 thang chu nha doi tang gia 1 trieu neu khong chiu thi duoi luon khong tra coc dung hay sai",
                "notes": "Không dấu, hỏi về tính pháp lý khi chủ nhà tự ý tăng giá thuê và đơn phương chấm dứt hợp đồng giữ cọc.",
            },
            {
                "turn": 2,
                "user_query_raw": "gio em muon lay lai 5 trieu tien coc va bat chu nha boi thuong vi duoi vo ly thi lam the nao, co kien ra cong an duoc khong",
                "notes": "Hỏi về cách giải quyết tranh chấp (hòa giải tại UBND xã / khởi kiện Tòa án nhân dân cấp huyện).",
            }
        ]
    },
    {
        "id": "journey_4_traffic",
        "domain": "Giao thông đường bộ",
        "user_profile": "Tài xế/người đi xe máy bị CSGT dừng xe kiểm tra nồng độ cồn và phạt vượt đèn.",
        "turns": [
            {
                "turn": 1,
                "user_query_raw": "toi vua bi csgt bat vi uong 2 lon bia thoi ra nong do con voi vuot den vang thi bi phat bao nhieu tien, co bi giu xe giu bang lai khong",
                "notes": "Không dấu, hỏi mức phạt nồng độ cồn xe máy/ô tô theo Nghị định 100/2019/NĐ-CP & NĐ 123/2021/NĐ-CP.",
            }
        ]
    },
    {
        "id": "journey_5_business_setup",
        "domain": "Khởi nghiệp & Thuế hộ kinh doanh",
        "user_profile": "Người mới kinh doanh muốn mở quán trà sữa nhỏ, chưa biết gì về thủ tục pháp lý, đăng ký kinh doanh và thuế.",
        "turns": [
            {
                "turn": 1,
                "user_query_raw": "minh dinh mo quan tra sua nho o quan 1 thi phai dang ky ho kinh doanh hay cong ty, moi thang dong thue the nao co can giay vsatp khong",
                "notes": "Không dấu, so sánh Hộ kinh doanh vs Công ty, điều kiện ATTP và nghĩa vụ thuế.",
            },
            {
                "turn": 2,
                "user_query_raw": "doanh thu uoc tinh tam 50 trieu mot thang thi dong thue gi va het khoang bao nhieu tien moi thang",
                "notes": "Hỏi về thuế khoán hộ kinh doanh (ngưỡng 100 triệu/năm, thuế GTGT 3% + TNCN 1.5% đối với ngành dịch vụ ăn uống).",
            }
        ]
    }
]


async def run_simulation():
    print("=" * 80)
    print("STARTING REALISTIC LAYMAN USER JOURNEY SIMULATION (5 USE CASES)")
    print("Testing Natural Language, Unaccented Vietnamese, Layman Slang & Multi-turn")
    print("=" * 80)

    runner = EprAgentRunner(config=AgentRunConfig(max_steps=5))
    results_summary = []

    for journey_idx, journey in enumerate(JOURNEYS, start=1):
        print(f"\n\n{'#' * 80}")
        print(f"CASE {journey_idx}: [{journey['domain'].upper()}] - ID: {journey['id']}")
        print(f"User Persona: {journey['user_profile']}")
        print(f"{'#' * 80}")

        history: list[dict[str, Any]] = []
        journey_turns_data = []

        for turn_data in journey["turns"]:
            turn_num = turn_data["turn"]
            query = turn_data["user_query_raw"]
            notes = turn_data["notes"]

            print(f"\n--- [Turn {turn_num}] User Input (Raw): ---")
            print(f"Query: \"{query}\"")
            print(f"Notes: {notes}")
            print(f"Executing Agent ReAct Cognitive Loop...")

            steps_log = []
            final_result = None

            async for event in runner.stream(query, history=history):
                event_type = event.get("type")
                if event_type == "agent_tool_call":
                    tool = event.get("tool")
                    args = event.get("args")
                    print(f"  ⚡ Step {event.get('step')}: [TOOL CALL] -> `{tool}`(args={json.dumps(args, ensure_ascii=False)})")
                    steps_log.append({"action": "call", "tool": tool, "args": args})
                elif event_type == "agent_tool_result":
                    tool = event.get("tool")
                    status = event.get("status")
                    lat = event.get("latency_ms")
                    print(f"  📥 Step {event.get('step')}: [OBSERVATION] <- `{tool}` status={status} (latency={lat}ms)")
                    steps_log.append({"action": "result", "tool": tool, "status": status, "latency_ms": lat})
                elif event_type == "agent_complete":
                    final_result = event.get("result")

            answer_text = final_result.answer if final_result else ""
            term_reason = final_result.termination_reason if final_result else "none"
            evidence_count = len(final_result.evidence) if final_result else 0
            steps_taken = final_result.steps_taken if final_result else 0

            print(f"\n[Agent Final Answer for Turn {turn_num}]:")
            print("-" * 60)
            print(answer_text)
            print("-" * 60)
            print(f"Termination Reason: {term_reason} | Steps Taken: {steps_taken} | Evidence Docs Found: {evidence_count}")

            # Append to history for multi-turn
            history.append({"role": "user", "content": query})
            history.append({"role": "assistant", "content": answer_text})

            journey_turns_data.append({
                "turn": turn_num,
                "query": query,
                "notes": notes,
                "steps": steps_log,
                "answer": answer_text,
                "termination_reason": term_reason,
                "steps_taken": steps_taken,
                "evidence_count": evidence_count,
            })

        results_summary.append({
            "id": journey["id"],
            "domain": journey["domain"],
            "user_profile": journey["user_profile"],
            "turns": journey_turns_data,
        })

    # Save complete simulation report to JSON
    output_path = Path("tests/eval/results_layman_journeys_simulation.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results_summary, f, ensure_ascii=False, indent=2)

    print(f"\n\n{'=' * 80}")
    print(f"SIMULATION COMPLETED SUCCESSFULLY! Saved report to: {output_path}")
    print(f"{'=' * 80}")


if __name__ == "__main__":
    asyncio.run(run_simulation())
