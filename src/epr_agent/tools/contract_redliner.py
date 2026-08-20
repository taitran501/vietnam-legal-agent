"""Contract Redlining and Legal Risk Matrix Analyzer.

Performs automated clause-by-clause scrutiny against Vietnamese statutory prohibitions:
1. Commercial penalties exceeding 8% (Điều 301 Luật Thương mại 2005).
2. Loan & overdue interest exceeding 20%/year (Điều 468 Bộ luật Dân sự 2015).
3. Labor probation exceeding statutory limits (Điều 25 Bộ luật Lao động 2019).
4. Unilateral wage withholding & statutory benefit denials (Điều 102 & Điều 17 BLLĐ).
5. Land & Housing deposit agreements lacking spousal / co-owner consent (Luật Hôn nhân & Gia đình & Luật Đất đai).
6. Total limitation of liability for intentional breach or bodily harm (Điều 360 BLDS).
7. Invalid dispute dispute resolution / jurisdiction clauses (BLTTDS & Luật Trọng tài thương mại).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Literal, TypedDict

from pydantic import BaseModel, Field

from epr_agent.tools.document_parser import ParsedClause


class ClauseReview(BaseModel):
    """Evaluation of an individual contract clause."""

    clause_id: str = Field(description="Mã điều khoản (ví dụ: Dieu_1, Dieu_5)")
    clause_title: str = Field(description="Tiêu đề điều khoản")
    original_text: str = Field(description="Nội dung điều khoản gốc")
    risk_level: Literal["high", "medium", "low", "safe"] = Field(
        description="Mức độ rủi ro: high (vi phạm luật/vô hiệu), medium (mập mờ/bất lợi), low (lưu ý nhỏ), safe (an toàn)"
    )
    statutory_conflict: str | None = Field(
        default=None, description="Căn cứ điều luật bị xung đột hoặc vi phạm (ví dụ: Điều 301 Luật Thương mại 2005)"
    )
    issue_description: str = Field(description="Phân tích rủi ro pháp lý và hậu quả nếu giữ nguyên")
    suggested_redline: str = Field(
        description="Đề xuất điều khoản sửa đổi hoàn chỉnh (Redline Revision) an toàn và bảo vệ quyền lợi"
    )


class ContractReviewReport(BaseModel):
    """Comprehensive legal risk matrix and redline report for an entire contract."""

    document_title: str = Field(description="Tên hợp đồng / tài liệu")
    contract_type: str = Field(description="Loại hợp đồng (Thương mại, Lao động, Thuê nhà, Đặt cọc, Dịch vụ...)")
    overall_risk: Literal["high", "medium", "low"] = Field(description="Đánh giá rủi ro tổng thể")
    total_clauses: int = Field(description="Tổng số điều khoản đã rà soát")
    high_risk_count: int = Field(default=0, description="Số điều khoản rủi ro cao")
    medium_risk_count: int = Field(default=0, description="Số điều khoản rủi ro trung bình")
    safe_clause_count: int = Field(default=0, description="Số điều khoản an toàn")
    executive_summary: str = Field(description="Tóm tắt nhận định của Luật sư rà soát")
    clause_reviews: list[ClauseReview] = Field(default_factory=list, description="Danh sách rà soát chi tiết từng điều")
    negotiation_strategy: list[str] = Field(default_factory=list, description="Chiến lược đàm phán sửa đổi hợp đồng")


class HeuristicRule(TypedDict):
    pattern: re.Pattern[str]
    check: Callable[[re.Match[str]], bool]
    conflict: str
    issue: str
    redline_hint: str


# Statutory heuristic detectors for fast offline / initial filtering
_HEURISTIC_RULES: list[HeuristicRule] = [
    {
        "pattern": re.compile(r"phạt\s*(?:vi phạm)?\s*(\d+)\s*%", re.IGNORECASE),
        "check": lambda m: int(m.group(1)) > 8,
        "conflict": "Điều 301 Luật Thương mại 2005",
        "issue": "Mức phạt vi phạm hợp đồng thương mại bị giới hạn tối đa 8% giá trị phần nghĩa vụ hợp đồng bị vi phạm. Thỏa thuận phạt quá 8% bị coi là trái luật.",
        "redline_hint": "Mức phạt vi phạm do hai bên thỏa thuận nhưng không quá 8% giá trị phần nghĩa vụ hợp đồng bị vi phạm theo quy định tại Điều 301 Luật Thương mại.",
    },
    {
        "pattern": re.compile(r"lãi\s*(?:suất|chậm trả)?\s*(\d+(?:\.\d+)?)\s*%\s*(?:/|mỗi)?\s*(?:tháng|năm)", re.IGNORECASE),
        "check": lambda m: float(m.group(1)) > 20.0 or ("tháng" in m.group(0).lower() and float(m.group(1)) > 1.66),
        "conflict": "Điều 468 Bộ luật Dân sự 2015",
        "issue": "Lãi suất thỏa thuận vượt quá trần luật định 20%/năm (tương đương ~1.66%/tháng). Phần lãi suất vượt quá không có hiệu lực pháp luật.",
        "redline_hint": "Trường hợp chậm thanh toán, bên vi phạm phải chịu lãi suất chậm trả bằng mức lãi suất tối đa theo quy định tại Điều 468 Bộ luật Dân sự (tối đa 20%/năm) tính trên số tiền và thời gian chậm trả.",
    },
    {
        "pattern": re.compile(r"thử\s*việc.*?\b(\d+)\s*(tháng|ngày)", re.IGNORECASE),
        "check": lambda m: (int(m.group(1)) > 60 if m.group(2).lower() == "ngày" else int(m.group(1)) > 2),
        "conflict": "Điều 25 Bộ luật Lao động 2019",
        "issue": "Thời gian thử việc tối đa là 60 ngày đối với công việc có trình độ cao đẳng trở lên, 30 ngày đối với trung cấp/nghiệp vụ, hoặc tối đa 180 ngày chỉ dành cho người quản lý doanh nghiệp.",
        "redline_hint": "Thời gian thử việc là 60 ngày đối với vị trí chuyên môn kể từ ngày bắt đầu làm việc, tuân thủ đúng quy định tại Điều 25 Bộ luật Lao động 2019.",
    },
    {
        "pattern": re.compile(r"(?:không\s+chịu\s+trách\s+nhiệm|miễn\s+trừ\s+toàn\s+bộ\s+trách\s+nhiệm\s+bồi\s+thường)", re.IGNORECASE),
        "check": lambda m: True,
        "conflict": "Điều 360 & Điều 361 Bộ luật Dân sự 2015",
        "issue": "Điều khoản miễn trừ trách nhiệm tuyệt đối trong mọi trường hợp (kể cả do lỗi cố ý hoặc gây thiệt hại đến tính mạng, sức khỏe) là vô hiệu theo quy định pháp luật dân sự.",
        "redline_hint": "Các bên chỉ được miễn trừ trách nhiệm bồi thường thiệt hại trong trường hợp sự kiện bất khả kháng hoặc do lỗi hoàn toàn của bên bị thiệt hại theo quy định tại Điều 351 Bộ luật Dân sự.",
    },
]


def review_contract_clauses_heuristic(
    clauses: list[ParsedClause],
    document_title: str = "Hợp đồng",
) -> ContractReviewReport:
    """Fast statutory heuristic scan on contract clauses."""
    reviews: list[ClauseReview] = []
    high_count = 0
    med_count = 0
    safe_count = 0

    for clause in clauses:
        detected = False
        text = clause.full_text

        for rule in _HEURISTIC_RULES:
            match = rule["pattern"].search(text)
            if match and rule["check"](match):
                reviews.append(
                    ClauseReview(
                        clause_id=clause.clause_id,
                        clause_title=clause.clause_title,
                        original_text=clause.full_text,
                        risk_level="high",
                        statutory_conflict=rule["conflict"],
                        issue_description=rule["issue"],
                        suggested_redline=rule["redline_hint"],
                    )
                )
                high_count += 1
                detected = True
                break

        if not detected:
            reviews.append(
                ClauseReview(
                    clause_id=clause.clause_id,
                    clause_title=clause.clause_title,
                    original_text=clause.full_text,
                    risk_level="safe",
                    statutory_conflict=None,
                    issue_description="Điều khoản phù hợp với quy tắc pháp lý thông thường, không phát hiện vi phạm điều cấm.",
                    suggested_redline=clause.full_text,
                )
            )
            safe_count += 1

    overall: Literal["high", "medium", "low"] = "high" if high_count > 0 else ("medium" if med_count > 0 else "low")
    summary = (
        f"Đã rà soát {len(clauses)} điều khoản của {document_title}. "
        f"Phát hiện {high_count} điều khoản rủi ro cao (vi phạm điều cấm luật định) cần sửa đổi trước khi ký kết."
        if high_count > 0
        else f"Đã rà soát {len(clauses)} điều khoản. Hợp đồng cơ bản tuân thủ quy định pháp luật Việt Nam."
    )

    strategy = [
        "Đề nghị đối tác áp dụng các câu chữ sửa đổi (Redline) đối với các điều khoản rủi ro cao.",
        "Làm rõ định nghĩa và cơ chế phạt vi phạm / lãi suất để tránh tranh chấp khi thanh lý hợp đồng.",
        "Đảm bảo các phụ lục đính kèm tuân thủ cùng các điều khoản chung.",
    ]

    return ContractReviewReport(
        document_title=document_title,
        contract_type="Hợp đồng pháp lý",
        overall_risk=overall,
        total_clauses=len(clauses),
        high_risk_count=high_count,
        medium_risk_count=med_count,
        safe_clause_count=safe_count,
        executive_summary=summary,
        clause_reviews=reviews,
        negotiation_strategy=strategy,
    )


_REDLINE_PROMPT = """Bạn là Luật sư Tranh tụng & Rà soát Hợp đồng Cấp cao (Senior Contract Redlining Counsel).
Nhiệm vụ của bạn là kiểm tra, rà soát chi tiết từng điều khoản hợp đồng được cung cấp và đối chiếu với pháp luật Việt Nam (Luật Thương mại, Bộ luật Dân sự, Bộ luật Lao động, Luật Đất đai, Luật Kinh doanh BĐS,...).

Tiêu chí đánh giá rủi ro:
- high: Điều khoản vi phạm điều cấm của luật (vô hiệu), phạt vượt quá mức luật định, thời gian thử việc trái luật, miễn trừ trách nhiệm trái luật, hoặc đẩy 100% rủi ro bất công cho một bên.
- medium: Điều khoản mập mờ, thiếu điều kiện giải trừ, bất lợi cho quyền lợi người dùng, thiếu cơ chế xử lý khi có biến động giá/chậm bàn giao.
- safe: Điều khoản chuẩn xác, cân bằng quyền và nghĩa vụ theo quy định pháp luật.

Đối với mỗi điều khoản có rủi ro (high/medium), hãy cung cấp:
1. Căn cứ điều luật cụ thể bị xung đột (statutory_conflict).
2. Phân tích rủi ro thực tế (issue_description).
3. Đề xuất viết lại điều khoản hoàn chỉnh (suggested_redline) chuẩn xác, chặt chẽ để người dùng gửi lại cho đối tác."""


async def review_contract_with_llm(
    clauses: list[ParsedClause],
    document_title: str = "Hợp đồng",
    contract_type: str = "Hợp đồng dân sự / thương mại",
) -> ContractReviewReport:
    """Analyze contract clauses with structured LLM review and statutory grounding."""
    from epr_agent.infra.llm_instances import get_llm_smart

    # If small or mock environment, fallback to heuristic
    if not clauses:
        return review_contract_clauses_heuristic(clauses, document_title)

    try:
        model = get_llm_smart().with_structured_output(ContractReviewReport)
        payload = {
            "document_title": document_title,
            "contract_type": contract_type,
            "clauses_to_review": [
                {
                    "clause_id": c.clause_id,
                    "clause_title": c.clause_title,
                    "text": c.full_text[:1500],
                }
                for c in clauses[:15]
            ],
        }

        report = await model.ainvoke(
            [
                ("system", _REDLINE_PROMPT),
                ("human", "Hãy rà soát hợp đồng sau:\n" + json.dumps(payload, ensure_ascii=False)),
            ]
        )
        if not isinstance(report, ContractReviewReport):
            report = ContractReviewReport.model_validate(report)
        return report
    except Exception:  # noqa: BLE001 - unavailable LLMs use the deterministic heuristic review
        # Graceful fallback to heuristic
        return review_contract_clauses_heuristic(clauses, document_title)
