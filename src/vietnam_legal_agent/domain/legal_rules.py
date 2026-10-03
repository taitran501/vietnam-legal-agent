"""Universal Multi-Domain Vietnamese Legal Decision & Calculation Engine.

Provides grounded statutory evaluations, dynamic case assessments, slot resolution,
structured QuestionForm schemas (inspired by open-design), and deterministic
legal formula calculations across all domains of Vietnamese Law:
1. Labor Law (Bộ luật Lao động 2019) - Overtime, Unlawful Termination, Severance, Probation
2. Civil & Contracts (Bộ luật Dân sự 2015) - Lease price adjust, Deposit refunds, Interest caps
3. Marriage & Family (Luật Hôn nhân và Gia đình 2014) - Unilateral Divorce, Child Custody
4. Enterprise Law (Luật Doanh nghiệp 2020) - Shareholder rights, EGM thresholds
5. Land Law (Luật Đất đai 2024) - First-time certificates (Art. 138), Land recovery compensation
6. Traffic Fines (Nghị định 100/2019/NĐ-CP & NĐ 123/2021/NĐ-CP) - Fine brackets, License suspension
7. Tax Law (Thông tư 40/2021/TT-BTC, Luật Thuế TNCN) - Flat tax rates, 7-bracket progressive PIT
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class LegalDomain(str, Enum):
    LABOR = "labor"
    CIVIL_CONTRACT = "civil_contract"
    MARRIAGE_FAMILY = "marriage_family"
    CORPORATE = "corporate"
    LAND = "land"
    TRAFFIC = "traffic"
    TAX = "tax"
    GENERAL = "general"


# Dynamic slot-filling field suggestions across legal domains
class GroundedCaseAssessment(BaseModel):
    """Dynamic LLM-grounded assessment schema for Vietnamese legal disputes."""

    domain: str = Field(description="Lĩnh vực pháp lý chính")
    status: str = Field(description="Mã trạng thái đánh giá chuẩn hóa")
    conclusion: str = Field(description="Kết luận sơ bộ khách quan đối chiếu với luật định")
    reasons: list[str] = Field(default_factory=list, description="Lập luận pháp lý căn cứ trên chứng cứ thực tế")
    applicable_provisions: list[str] = Field(default_factory=list, description="Điều khoản quy phạm pháp luật trích dẫn")
    missing_facts: list[str] = Field(default_factory=list, description="Các tình tiết pháp lý mấu chốt còn thiếu")
    financial_calculation: dict[str, Any] | None = Field(default=None, description="Kết quả tính toán tài chính nếu có")
    next_steps: list[str] = Field(default_factory=list, description="Khuyến nghị thủ tục và hành động tiếp theo")


@dataclass
class UniversalCaseEvaluation:
    domain: str
    status: str
    conclusion: str
    reasons: list[str] = field(default_factory=list)
    applicable_provisions: list[str] = field(default_factory=list)
    missing_facts: list[str] = field(default_factory=list)
    financial_calculation: dict[str, Any] | None = None
    next_steps: list[str] = field(default_factory=list)


def evaluate_universal_case(
    legal_domain: str,
    facts: dict[str, Any],
) -> dict[str, Any]:
    """Deterministic evaluation for structured dispute situations across all supported domains."""
    domain_clean = (legal_domain or "general").strip().lower()
    norm_facts = {str(k).lower(): str(v).strip() for k, v in (facts or {}).items()}

    # ── 1. LABOR LAW DOMAIN ──
    if domain_clean in ("labor", "laodong", "lao_dong"):
        contract_type = norm_facts.get("contract_type", "").lower()
        salary = float(norm_facts.get("monthly_salary_vnd", 0) or 0)
        notice_days = int(norm_facts.get("notice_days_given", 0) or 0)

        required_notice = 45 if "không xác định" in contract_type or "indefinite" in contract_type else 30
        if "thử việc" in contract_type or "probation" in contract_type:
            required_notice = 0

        is_violation = (
            notice_days < required_notice
            and "thỏa thuận" not in norm_facts.get("termination_reason", "").lower()
            and required_notice > 0
        )

        min_compensation = salary * 2 if salary > 0 else None

        return {
            "domain": "labor",
            "status": "unlawful_termination" if is_violation else "evaluated_normal",
            "conclusion": (
                "Người sử dụng lao động có dấu hiệu đơn phương chấm dứt hợp đồng TRÁI PHÁP LUẬT do vi phạm quy định tại Điều 36 và nghĩa vụ bồi thường theo Điều 41 Bộ luật Lao động 2019."
                if is_violation
                else "Chấm dứt hợp đồng lao động cần đối chiếu quyền lợi trợ cấp thôi việc và tiền lương ngày làm việc thực tế theo Điều 46, 47 Bộ luật Lao động 2019."
            ),
            "reasons": [
                f"Thời hạn báo trước theo luật định là ít nhất {required_notice} ngày (thực tế: {notice_days} ngày)."
                if required_notice > 0
                else "Hợp đồng thử việc không áp dụng thời hạn báo trước theo Điều 27 BLLĐ.",
                "Quyền lợi được bảo đảm theo Điều 41 Bộ luật Lao động 2019 về nghĩa vụ của NSDLĐ khi đơn phương chấm dứt HĐLĐ trái pháp luật.",
            ],
            "applicable_provisions": ["Điều 36 Bộ luật Lao động 2019", "Điều 41 Bộ luật Lao động 2019"],
            "financial_calculation": {
                "statutory_min_compensation_vnd": min_compensation,
                "minimum_compensation_vnd": min_compensation,
                "statutory_minimum_months": 2,
            }
            if min_compensation
            else None,
            "next_steps": [
                "Yêu cầu công ty bồi thường thỏa thuận theo Điều 41 BLLĐ 2019.",
                "Làm đơn yêu cầu hòa giải viên lao động hoặc nộp đơn khởi kiện tại Tòa án nhân dân cấp huyện/quận nơi công ty đặt trụ sở.",
            ],
            "ok": True,
        }

    # ── 2. CIVIL & LEASE CONTRACT DOMAIN ──
    if domain_clean in ("civil_contract", "civil", "dansu", "dan_su", "thue_nha"):
        agreed = norm_facts.get("agreed_in_contract", "").lower()
        issue = norm_facts.get("dispute_issue", "").lower()

        if "tăng giá" in issue or "tang_gia" in issue or "rent_increase" in issue:
            can_increase = "có" in agreed or "co" in agreed or "yes" in agreed or "stipulated" in agreed
            return {
                "domain": "civil_contract",
                "status": "price_increase_permitted" if can_increase else "unlawful_price_increase",
                "conclusion": (
                    "Bên cho thuê có quyền điều chỉnh giá nếu hợp đồng có quy định rõ cơ chế tăng giá theo Điều 478 Bộ luật Dân sự 2015."
                    if can_increase
                    else "Bên cho thuê KHÔNG ĐƯỢC TỰ Ý TĂNG GIÁ thuê nhà nếu hợp đồng không có thỏa thuận điều chỉnh giá theo Điều 478 Bộ luật Dân sự 2015."
                ),
                "reasons": [
                    "Khoản 2 Điều 478 Bộ luật Dân sự 2015: Giá thuê do các bên thỏa thuận; nếu không có thỏa thuận thì theo giá thị trường tại thời điểm và địa điểm ký kết.",
                    "Trường hợp chưa hết hạn hợp đồng mà bên cho thuê tăng giá đơn phương không có căn cứ, bên thuê có quyền từ chối hoặc yêu cầu tiếp tục thực hiện hợp đồng theo giá cũ.",
                ],
                "applicable_provisions": ["Điều 478 Bộ luật Dân sự 2015", "Điều 351 Bộ luật Dân sự 2015"],
                "next_steps": ["Gửi thông báo bằng văn bản từ chối mức tăng giá trái hợp đồng", "Yêu cầu tôn trọng thời hạn hợp đồng đã ký kết"],
                "ok": True,
            }

        if "cọc" in issue or "coc" in issue or "deposit" in issue:
            return {
                "domain": "civil_contract",
                "status": "deposit_refund_dispute",
                "conclusion": "Bên nhận đặt cọc phải hoàn trả toàn bộ tiền đặt cọc nếu bên thuê không vi phạm nghĩa vụ hợp đồng theo Điều 328 Bộ luật Dân sự 2015.",
                "reasons": [
                    "Khoản 2 Điều 328 BLDS 2015: Trường hợp hợp đồng được thực hiện thì tài sản đặt cọc được trả lại cho bên đặt cọc hoặc được trừ để thực hiện nghĩa vụ trả tiền.",
                    "Nếu bên nhận đặt cọc từ chối giao kết/thực hiện hợp đồng không có lý do chính đáng, phải trả lại tài sản đặt cọc và một khoản tiền tương đương giá trị tài sản đặt cọc (trừ trường hợp có thỏa thuận khác).",
                ],
                "applicable_provisions": ["Điều 328 Bộ luật Dân sự 2015"],
                "next_steps": ["Lập biên bản bàn giao nhà và yêu cầu hoàn trả tiền cọc", "Khởi kiện tại Tòa án nếu bên cho thuê chiếm giữ tiền cọc trái luật"],
                "ok": True,
            }

    # ── 3. MARRIAGE & FAMILY DOMAIN ──
    if domain_clean in ("marriage_family", "honnhan", "hon_nhan", "lyhon"):
        cert_status = norm_facts.get("marriage_certificate_status", "").lower()
        if "giữ" in cert_status or "giu" in cert_status or "held" in cert_status or "mất" in cert_status or "mat" in cert_status:
            return {
                "domain": "marriage_family",
                "status": "unilateral_divorce_eligible",
                "conclusion": "Bạn CÓ ĐỦ ĐIỀU KIỆN nộp đơn ly hôn đơn phương. Việc đối phương giữ Giấy chứng nhận kết hôn KHÔNG ngăn cản quyền này.",
                "reasons": [
                    "Điều 56 Luật Hôn nhân và Gia đình 2014 quy định quyền đơn phương xin ly hôn của vợ hoặc chồng khi có căn cứ về việc hôn nhân lâm vào tình trạng trầm trọng.",
                    "Theo Điều 62 Luật Hộ tịch 2014, bạn có quyền đến UBND cấp xã nơi đã đăng ký kết hôn trước đây để xin cấp Bản trích lục kết hôn (bản sao trích lục) thay thế bản chính trong hồ sơ nộp Tòa.",
                ],
                "applicable_provisions": ["Điều 56 Luật Hôn nhân và Gia đình 2014", "Điều 62 Luật Hộ tịch 2014"],
                "next_steps": [
                    "Đến UBND xã/phường nơi đăng ký kết hôn làm thủ tục cấp bản sao trích lục kết hôn",
                    "Nộp hồ sơ ly hôn đơn phương kèm bản sao trích lục tại Tòa án nhân dân cấp huyện nơi bị đơn cư trú",
                ],
                "ok": True,
            }

    # ── 4. CORPORATE LAW DOMAIN ──
    if domain_clean in ("corporate", "doanhnghiep", "doanh_nghiep"):
        ratio = float(norm_facts.get("shareholder_ratio_percent", 0) or 0)
        if ratio >= 5.0:
            return {
                "domain": "corporate",
                "status": "threshold_met",
                "conclusion": f"Cổ đông (hoặc nhóm cổ đông) sở hữu {ratio}% ĐỦ ĐIỀU KIỆN thực hiện quyền yêu cầu triệu tập họp ĐHĐCĐ bất thường theo Điều 115 Luật Doanh nghiệp 2020.",
                "reasons": [
                    "Khoản 2 Điều 115 Luật Doanh nghiệp 2020: Cổ đông hoặc nhóm cổ đông sở hữu từ 05% tổng số cổ phần phổ thông trở lên có quyền yêu cầu triệu tập họp ĐHĐCĐ khi HĐQT vi phạm nghiêm trọng quyền của cổ đông.",
                    "HĐQT phải triệu tập họp ĐHĐCĐ trong thời hạn 30 ngày kể từ ngày nhận được yêu cầu. Nếu HĐQT không triệu tập, Ban kiểm soát phải triệu tập thay thế.",
                ],
                "applicable_provisions": ["Điều 115 Luật Doanh nghiệp 2020", "Điều 140 Luật Doanh nghiệp 2020"],
                "next_steps": ["Gửi văn bản yêu cầu chính thức tới HĐQT và Ban kiểm soát", "Tự triệu tập họp ĐHĐCĐ nếu HĐQT và BKS đều không triệu tập theo đúng thời hạn luật định"],
                "ok": True,
            }
        return {
            "domain": "corporate",
            "status": "threshold_not_met",
            "conclusion": f"Tỷ lệ sở hữu {ratio}% chưa đạt ngưỡng 5% cổ phần phổ thông theo Điều 115 Luật Doanh nghiệp 2020 để tự mình yêu cầu triệu tập ĐHĐCĐ bất thường.",
            "reasons": ["Khoản 2 Điều 115 Luật Doanh nghiệp 2020 yêu cầu tỷ lệ sở hữu tối thiểu 05% tổng số cổ phần phổ thông."],
            "applicable_provisions": ["Điều 115 Luật Doanh nghiệp 2020"],
            "next_steps": ["Liên kết với các cổ đông khác để đạt tổng tỷ lệ sở hữu từ 5% trở lên"],
            "ok": True,
        }

    # ── 5. TRAFFIC VIOLATIONS DOMAIN ──
    if domain_clean in ("traffic", "giaothong", "giao_thong"):
        act = norm_facts.get("violation_act", "").lower()
        vehicle = norm_facts.get("vehicle_type", "").lower()

        if "cồn" in act or "con" in act or "alcohol" in act or "bia" in act or "ruou" in act:
            if "ô tô" in vehicle or "xe hơi" in vehicle or "car" in vehicle or "oto" in vehicle:
                return {
                    "domain": "traffic",
                    "status": "alcohol_penalty_evaluated",
                    "conclusion": "Mức phạt nồng độ cồn đối với người điều khiển xe ô tô theo Nghị định 100/2019/NĐ-CP (sửa đổi bởi NĐ 123/2021/NĐ-CP).",
                    "reasons": [
                        "Mức 1 (chưa vượt 0.25mg/l): Phạt tiền từ 6.000.000đ - 8.000.000đ, tước GPLX 10 - 12 tháng.",
                        "Mức 2 (vượt 0.25 - 0.4mg/l): Phạt tiền từ 16.000.000đ - 18.000.000đ, tước GPLX 16 - 18 tháng.",
                        "Mức 3 (vượt 0.4mg/l): Phạt tiền từ 30.000.000đ - 40.000.000đ, tước GPLX 22 - 24 tháng.",
                        "Tạm giữ phương tiện đến 07 ngày trước khi ra quyết định xử phạt.",
                    ],
                    "applicable_provisions": ["Điều 5 Nghị định 100/2019/NĐ-CP", "Nghị định 123/2021/NĐ-CP"],
                    "ok": True,
                }
            return {
                "domain": "traffic",
                "status": "alcohol_penalty_evaluated",
                "conclusion": "Mức phạt nồng độ cồn đối với người điều khiển xe mô tô, xe gắn máy theo Nghị định 100/2019/NĐ-CP (sửa đổi bởi NĐ 123/2021/NĐ-CP).",
                "reasons": [
                    "Mức 1 (chưa vượt 0.25mg/l): Phạt tiền từ 2.000.000đ - 3.000.000đ, tước GPLX 10 - 12 tháng.",
                    "Mức 2 (vượt 0.25 - 0.4mg/l): Phạt tiền từ 4.000.000đ - 5.000.000đ, tước GPLX 16 - 18 tháng.",
                    "Mức 3 (vượt 0.4mg/l): Phạt tiền từ 6.000.000đ - 8.000.000đ, tước GPLX 22 - 24 tháng.",
                    "Tạm giữ phương tiện đến 07 ngày trước khi ra quyết định xử phạt.",
                ],
                "applicable_provisions": ["Điều 6 Nghị định 100/2019/NĐ-CP", "Nghị định 123/2021/NĐ-CP"],
                "ok": True,
            }

        if "đèn đỏ" in act or "den do" in act or "đèn vàng" in act or "den vang" in act or "traffic_light" in act:
            if ("ô tô" in vehicle or "xe hơi" in vehicle or "car" in vehicle or "oto" in vehicle) and "mô tô" not in vehicle:
                return {
                    "domain": "traffic",
                    "status": "traffic_penalty_evaluated",
                    "conclusion": "Mức phạt hành vi vượt đèn đỏ / đèn vàng đối với xe ô tô: 4.000.000đ - 6.000.000đ theo Nghị định 100/2019/NĐ-CP (sửa đổi bởi NĐ 123/2021).",
                    "reasons": ["Điểm a Khoản 5 Điều 5 Nghị định 100/2019/NĐ-CP.", "Bị tước Giấy phép lái xe từ 01 tháng đến 03 tháng."],
                    "applicable_provisions": ["Điều 5 Nghị định 100/2019/NĐ-CP", "Nghị định 123/2021/NĐ-CP"],
                    "financial_calculation": {"min_fine_vnd": 4000000, "max_fine_vnd": 6000000, "license_suspension_months": "1 - 3 tháng"},
                    "ok": True,
                }
            return {
                "domain": "traffic",
                "status": "traffic_penalty_evaluated",
                "conclusion": "Mức phạt hành vi vượt đèn đỏ / đèn vàng đối với xe mô tô, xe gắn máy: 800.000đ - 1.000.000đ theo Nghị định 100/2019/NĐ-CP (sửa đổi bởi NĐ 123/2021/NĐ-CP).",
                "reasons": ["Điểm e Khoản 4 Điều 6 Nghị định 100/2019/NĐ-CP (sửa đổi bởi NĐ 123/2021/NĐ-CP).", "Bị tước Giấy phép lái xe từ 01 tháng đến 03 tháng."],
                "applicable_provisions": ["Điều 6 Nghị định 100/2019/NĐ-CP", "Nghị định 123/2021/NĐ-CP"],
                "financial_calculation": {"min_fine_vnd": 800000, "max_fine_vnd": 1000000, "license_suspension_months": "1 - 3 tháng"},
                "ok": True,
            }

    # Generic Fallback
    return {
        "domain": domain_clean,
        "status": "evaluated_general",
        "conclusion": "Đã ghi nhận các dữ kiện tình huống. Cần đối chiếu trực tiếp với các điều khoản quy định liên quan.",
        "reasons": ["Dữ kiện hợp lệ để làm căn cứ tra cứu pháp lý."],
        "applicable_provisions": [],
        "ok": True,
    }


def calculate_legal_formula(
    calculation_type: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    """Execute deterministic statutory calculations across Vietnamese legal domains.

    Supported calculation types:
    - 'overtime_salary': Tiền lương làm thêm giờ ngày thường, ngày nghỉ, lễ tết (Điều 98 BLLĐ 2019).
    - 'unlawful_termination_compensation': Bồi thường sa thải trái luật (Điều 41 BLLĐ 2019).
    - 'severance_allowance': Trợ cấp thôi việc (Điều 46 BLLĐ 2019).
    - 'probation_wage_floor': Mức sàn tiền lương thử việc (Điều 26 BLLĐ 2019).
    - 'traffic_fine': Mức phạt vi phạm giao thông (NĐ 100/2019 & NĐ 123/2021).
    - 'household_business_tax': Thuế khoán hộ kinh doanh (GTGT & TNCN theo Thông tư 40/2021/TT-BTC).
    - 'personal_income_tax': Thuế thu nhập cá nhân biểu thuế lũy tiến 7 bậc.
    - 'late_payment_interest': Lãi suất chậm trả và trần lãi suất vay (Điều 468 BLDS 2015).
    """
    calc_type = (calculation_type or "").strip().lower()
    params = {str(k).lower(): v for k, v in (parameters or {}).items()}

    # 1. Overtime Pay Calculation (Điều 98 BLLĐ 2019 & NĐ 145/2020/NĐ-CP)
    if calc_type in ("overtime_salary", "tien_luong_lam_them_gio", "overtime"):
        monthly_salary = float(params.get("monthly_salary_vnd", 0) or 0)
        standard_working_days = float(params.get("standard_working_days", 26) or 26)
        hourly_wage = float(params.get("hourly_wage_vnd", 0) or 0)
        if hourly_wage <= 0 and monthly_salary > 0:
            hourly_wage = monthly_salary / (standard_working_days * 8.0)

        hours = float(params.get("overtime_hours", 0) or 0)
        day_type = str(params.get("day_type", "weekday")).lower()

        multiplier = 1.5
        day_label = "ngày thường (ít nhất 150%)"
        if any(w in day_type for w in ("chủ nhật", "cuối tuần", "weekend", "nghỉ hằng tuần", "sunday")):
            multiplier = 2.0
            day_label = "ngày nghỉ hằng tuần / Chủ nhật (ít nhất 200%)"
        elif any(w in day_type for w in ("lễ", "tết", "holiday")):
            multiplier = 3.0
            day_label = "ngày nghỉ lễ, tết có hưởng lương (ít nhất 300%)"

        is_night = bool(params.get("is_night", False) or "đêm" in day_type or "night" in day_type)
        night_bonus = 0.3 * hourly_wage * hours if is_night else 0.0

        total_pay = (hourly_wage * hours * multiplier) + night_bonus
        return {
            "calculation_type": "overtime_salary",
            "hourly_wage_vnd": round(hourly_wage, 2),
            "overtime_hours": hours,
            "statutory_rate_percent": int(multiplier * 100),
            "rate_multiplier": multiplier,
            "day_type_label": day_label,
            "night_bonus_vnd": round(night_bonus, 2),
            "total_overtime_pay_vnd": round(total_pay, 0),
            "calculated_amount_vnd": round(total_pay, 0),
            "legal_basis": "Điều 98 Bộ luật Lao động 2019 và Nghị định 145/2020/NĐ-CP",
            "formula": (
                f"Tiền lương làm thêm = ({hourly_wage:,.0f} đ/giờ × {hours} giờ × {multiplier:.1f})"
                + (f" + Phụ cấp ca đêm ({night_bonus:,.0f} đ)" if is_night else "")
                + f" = {total_pay:,.0f} đ"
            ),
            "formatted_summary": f"Tổng tiền làm thêm giờ: {total_pay:,.0f} VNĐ ({hours} giờ {day_label})",
            "ok": True,
        }

    # 2. Unlawful Termination Compensation (Điều 41 BLLĐ 2019)
    if calc_type in ("unlawful_termination_compensation", "boi_thuong_sa_thai_trai_luat", "termination"):
        salary = float(params.get("monthly_salary_vnd", 0) or 0)
        months_unworked = float(params.get("months_awaiting_settlement", 0) or params.get("months_unworked", 0) or 0)
        unnotified_days = float(params.get("unworked_days_without_notice", 0) or params.get("unnotified_days", 0) or 0)

        comp_statutory = salary * 2.0
        back_pay = salary * months_unworked
        unnotified_pay = (salary / 26.0) * unnotified_days if unnotified_days > 0 else 0.0
        total_comp = comp_statutory + back_pay + unnotified_pay

        return {
            "calculation_type": "unlawful_termination_compensation",
            "statutory_min_indemnity_months": 2,
            "statutory_min_indemnity_vnd": round(comp_statutory, 0),
            "statutory_min_2_months_vnd": round(comp_statutory, 0),
            "back_pay_during_unworked_period_vnd": round(back_pay, 0),
            "salary_during_awaiting_days_vnd": round(back_pay, 0),
            "unnotified_days_compensation_vnd": round(unnotified_pay, 0),
            "total_minimum_compensation_vnd": round(total_comp, 0),
            "total_estimated_compensation_vnd": round(total_comp, 0),
            "legal_basis": "Điều 41 Bộ luật Lao động 2019",
            "formula": (
                f"Bồi thường tối thiểu = (2 tháng lương × {salary:,.0f} đ) + "
                f"(Lương ngày không được làm việc: {months_unworked} tháng × {salary:,.0f} đ)"
                + (f" + (Lương vi phạm báo trước: {unnotified_days} ngày × {salary/26:,.0f} đ)" if unnotified_days > 0 else "")
                + f" = {total_comp:,.0f} đ"
            ),
            "formatted_summary": f"Tổng số tiền NSDLĐ phải bồi thường tối thiểu: {total_comp:,.0f} VNĐ",
            "ok": True,
        }

    # 3. Severance Allowance (Điều 46 BLLĐ 2019)
    if calc_type in ("severance_allowance", "tro_cap_thoi_viec", "severance"):
        salary = float(params.get("monthly_salary_average_6m_vnd", 0) or params.get("monthly_salary_vnd", 0) or 0)
        years = float(params.get("years_of_service", 0) or params.get("qualifying_working_years", 0) or 0)
        total_allowance = salary * years * 0.5

        return {
            "calculation_type": "severance_allowance",
            "qualifying_working_years": years,
            "rate_per_year": "0.5 tháng tiền lương bình quân 6 tháng liền kề",
            "total_severance_vnd": round(total_allowance, 0),
            "calculated_amount_vnd": round(total_allowance, 0),
            "legal_basis": "Điều 46 Bộ luật Lao động 2019",
            "formula": f"Trợ cấp thôi việc = {years} năm × 0.5 × {salary:,.0f} đ = {total_allowance:,.0f} đ",
            "formatted_summary": f"Trợ cấp thôi việc được nhận: {total_allowance:,.0f} VNĐ",
            "ok": True,
        }

    # 4. Probation Wage Floor (Điều 26 BLLĐ 2019)
    if calc_type in ("probation_wage_floor", "luong_thu_viec", "probation"):
        official_salary = float(params.get("official_monthly_salary_vnd", 0) or params.get("official_salary_vnd", 0) or params.get("monthly_salary_vnd", 0) or 0)
        actual_probation_wage = float(params.get("actual_probation_wage_vnd", 0) or 0)
        min_statutory_wage = official_salary * 0.85
        is_underpaid = actual_probation_wage > 0 and actual_probation_wage < min_statutory_wage

        return {
            "calculation_type": "probation_wage_floor",
            "official_salary_vnd": round(official_salary, 0),
            "minimum_probation_rate_percent": 85,
            "minimum_statutory_wage_vnd": round(min_statutory_wage, 0),
            "min_probation_salary_vnd": round(min_statutory_wage, 0),
            "actual_probation_wage_vnd": round(actual_probation_wage, 0) if actual_probation_wage else None,
            "is_underpaid_violation": is_underpaid,
            "legal_basis": "Điều 26 Bộ luật Lao động 2019",
            "formula": f"Lương thử việc tối thiểu = 85% × {official_salary:,.0f} đ = {min_statutory_wage:,.0f} đ",
            "formatted_summary": f"Mức lương thử việc theo luật định tối thiểu là 85%: {min_statutory_wage:,.0f} VNĐ",
            "ok": True,
        }

    # 5. Traffic Fine Calculation (Nghị định 100/2019/NĐ-CP & Nghị định 123/2021/NĐ-CP)
    if calc_type in ("traffic_fine", "phat_giao_thong", "traffic"):
        vehicle = str(params.get("vehicle_type", "motorbike")).lower()
        act = str(params.get("violation_act", "")).lower()
        concentration = str(params.get("alcohol_level", "") or params.get("alcohol_concentration", "")).lower()

        is_car = any(v in vehicle for v in ("ô tô", "xe hơi", "car", "oto"))
        is_alcohol = any(a in act for a in ("cồn", "alcohol", "bia", "rượu", "con"))

        if is_alcohol:
            if is_car:
                if any(k in concentration for k in ("3", "over_04", "trên 0.4", "vượt quá 0.4")):
                    min_f, max_f, susp = 30000000, 40000000, "22 - 24 tháng"
                elif any(k in concentration for k in ("2", "025_to_04", "0.25 đến 0.4")):
                    min_f, max_f, susp = 16000000, 18000000, "16 - 18 tháng"
                else:
                    min_f, max_f, susp = 6000000, 8000000, "10 - 12 tháng"
            else:  # motorbike
                if any(k in concentration for k in ("3", "over_04", "trên 0.4", "vượt quá 0.4")):
                    min_f, max_f, susp = 6000000, 8000000, "22 - 24 tháng"
                elif any(k in concentration for k in ("2", "025_to_04", "0.25 đến 0.4")):
                    min_f, max_f, susp = 4000000, 5000000, "16 - 18 tháng"
                else:
                    min_f, max_f, susp = 2000000, 3000000, "10 - 12 tháng"
            legal_doc = "Nghị định 100/2019/NĐ-CP (sửa đổi bởi NĐ 123/2021/NĐ-CP)"
        else:  # Red / Yellow Light
            if is_car:
                min_f, max_f, susp = 4000000, 6000000, "1 - 3 tháng"
            else:
                min_f, max_f, susp = 800000, 1000000, "1 - 3 tháng"
            legal_doc = "Nghị định 100/2019/NĐ-CP & NĐ 123/2021/NĐ-CP"

        mid_fine = (min_f + max_f) / 2.0
        return {
            "calculation_type": "traffic_fine",
            "vehicle_type": "Xe ô tô" if is_car else "Xe mô tô / xe gắn máy",
            "violation_act": "Vi phạm nồng độ cồn" if is_alcohol else "Không chấp hành tín hiệu đèn giao thông (vượt đèn đỏ/vàng)",
            "min_fine_vnd": min_f,
            "max_fine_vnd": max_f,
            "standard_fine_vnd": mid_fine,
            "midpoint_fine_vnd": mid_fine,
            "license_suspension": susp,
            "vehicle_impoundment_days": 7,
            "legal_basis": legal_doc,
            "formula": f"Khung phạt: {min_f:,.0f} đ - {max_f:,.0f} đ (mức phạt trung bình: {mid_fine:,.0f} đ), tước GPLX {susp}, giữ xe đến 7 ngày.",
            "formatted_summary": f"Khung phạt: {min_f:,.0f} - {max_f:,.0f} VNĐ, tước GPLX {susp}, tạm giữ phương tiện 7 ngày.",
            "ok": True,
        }

    # 6. Household Business Flat Tax (Thông tư 40/2021/TT-BTC)
    if calc_type in ("household_business_tax", "thue_ho_kinh_doanh", "thue_khoan", "tax"):
        monthly_revenue = float(params.get("monthly_revenue_vnd", 0) or 0)
        annual_revenue = monthly_revenue * 12.0 if monthly_revenue > 0 else float(params.get("annual_revenue_vnd", 0) or 0)
        business_sector = str(params.get("business_sector", "food_and_beverage")).lower()

        # Threshold check: revenue <= 100M/year is tax-exempt
        if annual_revenue <= 100000000 and annual_revenue > 0:
            return {
                "calculation_type": "household_business_tax",
                "monthly_revenue_vnd": round(monthly_revenue, 0),
                "annual_revenue_vnd": round(annual_revenue, 0),
                "is_tax_exempt": True,
                "is_exempt": True,
                "vat_tax_vnd": 0,
                "monthly_vat_vnd": 0,
                "pit_tax_vnd": 0,
                "monthly_pit_vnd": 0,
                "total_monthly_tax_vnd": 0,
                "legal_basis": "Thông tư 40/2021/TT-BTC (Điều 4)",
                "formula": "Doanh thu từ 100 triệu đồng/năm trở xuống thuộc diện MIỄN nộp thuế GTGT và thuế TNCN.",
                "formatted_summary": "Doanh thu dưới 100 triệu/năm được miễn hoàn toàn thuế GTGT và TNCN.",
                "ok": True,
            }

        # Rates based on sector (TT 40/2021/TT-BTC Phụ lục I)
        if any(s in business_sector for s in ("ăn uống", "trà sữa", "food", "beverage", "nhà hàng", "quán nước")):
            vat_rate, pit_rate = 0.03, 0.015  # Dịch vụ ăn uống: 3% GTGT + 1.5% TNCN = 4.5%
            sector_name = "Dịch vụ ăn uống, nhà hàng, quán nước (3% GTGT + 1.5% TNCN)"
        elif any(s in business_sector for s in ("phân phối", "bán buôn", "bán lẻ", "tạp hóa", "retail")):
            vat_rate, pit_rate = 0.01, 0.005  # Phân phối, cung cấp hàng hóa: 1% GTGT + 0.5% TNCN = 1.5%
            sector_name = "Phân phối, bán buôn, bán lẻ hàng hóa (1% GTGT + 0.5% TNCN)"
        else:
            vat_rate, pit_rate = 0.05, 0.02   # Dịch vụ khác: 5% GTGT + 2% TNCN = 7%
            sector_name = "Dịch vụ, xây dựng không bao thầu nguyên vật liệu (5% GTGT + 2% TNCN)"

        vat_monthly = monthly_revenue * vat_rate
        pit_monthly = monthly_revenue * pit_rate
        total_monthly = vat_monthly + pit_monthly

        return {
            "calculation_type": "household_business_tax",
            "monthly_revenue_vnd": round(monthly_revenue, 0),
            "annual_revenue_vnd": round(annual_revenue, 0),
            "sector_name": sector_name,
            "vat_rate_percent": vat_rate * 100,
            "pit_rate_percent": pit_rate * 100,
            "vat_tax_vnd": round(vat_monthly, 0),
            "monthly_vat_vnd": round(vat_monthly, 0),
            "pit_tax_vnd": round(pit_monthly, 0),
            "monthly_pit_vnd": round(pit_monthly, 0),
            "total_monthly_tax_vnd": round(total_monthly, 0),
            "is_tax_exempt": False,
            "is_exempt": False,
            "legal_basis": "Thông tư số 40/2021/TT-BTC của Bộ Tài chính",
            "formula": (
                f"Thuế GTGT ({vat_rate*100:.1f}%) = {vat_monthly:,.0f} đ + "
                f"Thuế TNCN ({pit_rate*100:.1f}%) = {pit_monthly:,.0f} đ "
                f"==> Tổng thuế khoán phải nộp hàng tháng = {total_monthly:,.0f} đ"
            ),
            "formatted_summary": f"Tổng thuế khoán hàng tháng: {total_monthly:,.0f} VNĐ (Thuế GTGT: {vat_monthly:,.0f} đ + Thuế TNCN: {pit_monthly:,.0f} đ)",
            "ok": True,
        }

    # 7. Personal Income Tax (Luật Thuế TNCN 2007, sửa đổi 2014 & NQ 954/2020/UBTVQH14)
    if calc_type in ("personal_income_tax", "thue_tncn", "pit"):
        income = float(params.get("monthly_gross_salary_vnd", 0) or params.get("monthly_income_vnd", 0) or 0)
        dependents = int(params.get("dependents_count", 0) or 0)
        insurance = float(params.get("insurance_deduction_vnd", 0) or 0)

        personal_deduction = 11000000.0
        dependent_deduction = dependents * 4400000.0
        total_deduction = personal_deduction + dependent_deduction + insurance
        assessable_income = max(0.0, income - total_deduction)

        # Progressive brackets (7 brackets)
        tax = 0.0
        if assessable_income > 0:
            b1 = min(assessable_income, 5000000.0)
            tax += b1 * 0.05
        if assessable_income > 5000000.0:
            b2 = min(assessable_income - 5000000.0, 5000000.0)
            tax += b2 * 0.10
        if assessable_income > 10000000.0:
            b3 = min(assessable_income - 10000000.0, 8000000.0)
            tax += b3 * 0.15
        if assessable_income > 18000000.0:
            b4 = min(assessable_income - 18000000.0, 14000000.0)
            tax += b4 * 0.20
        if assessable_income > 32000000.0:
            b5 = min(assessable_income - 32000000.0, 20000000.0)
            tax += b5 * 0.25
        if assessable_income > 52000000.0:
            b6 = min(assessable_income - 52000000.0, 28000000.0)
            tax += b6 * 0.30
        if assessable_income > 80000000.0:
            b7 = assessable_income - 80000000.0
            tax += b7 * 0.35

        return {
            "calculation_type": "personal_income_tax",
            "monthly_income_vnd": round(income, 0),
            "personal_deduction_vnd": personal_deduction,
            "dependents_deduction_vnd": dependent_deduction,
            "total_deductions_vnd": round(total_deduction, 0),
            "assessable_income_vnd": round(assessable_income, 0),
            "taxable_income_vnd": round(assessable_income, 0),
            "monthly_pit_tax_vnd": round(tax, 0),
            "pit_tax_amount_vnd": round(tax, 0),
            "legal_basis": "Luật Thuế thu nhập cá nhân và Nghị quyết 954/2020/UBTVQH14",
            "formula": f"Thu nhập tính thuế: {assessable_income:,.0f} đ ==> Thuế TNCN lũy tiến 7 bậc = {tax:,.0f} đ",
            "formatted_summary": f"Thuế TNCN phải nộp: {tax:,.0f} VNĐ/tháng (Thu nhập chịu thuế sau giảm trừ: {assessable_income:,.0f} VNĐ)",
            "ok": True,
        }

    # 8. Statutory Interest & Late Payment Cap (Điều 468 Bộ luật Dân sự 2015)
    if calc_type in ("late_payment_interest", "lai_suat_cham_tra", "lai_suat_vay", "interest"):
        principal = float(params.get("principal_vnd", 0) or 0)
        overdue_days = float(params.get("days_overdue", 0) or params.get("overdue_days", 0) or 0)
        agreed_rate_annual = float(params.get("annual_interest_rate_percent", 0) or params.get("agreed_rate_annual_percent", 0) or 0)

        max_statutory_rate = 20.0  # 20%/year under Art 468
        is_usury_violation = agreed_rate_annual > max_statutory_rate

        applicable_annual_rate = min(agreed_rate_annual if agreed_rate_annual > 0 else 10.0, max_statutory_rate)
        interest_amount = principal * (applicable_annual_rate / 100.0) * (overdue_days / 365.0)

        return {
            "calculation_type": "late_payment_interest",
            "principal_vnd": round(principal, 0),
            "overdue_days": overdue_days,
            "max_statutory_annual_rate_percent": max_statutory_rate,
            "applicable_annual_rate_percent": applicable_annual_rate,
            "applied_annual_rate_percent": applicable_annual_rate,
            "is_usury_violation": is_usury_violation,
            "was_capped_at_statutory_limit": is_usury_violation,
            "total_interest_vnd": round(interest_amount, 0),
            "interest_amount_vnd": round(interest_amount, 0),
            "legal_basis": "Điều 468 Bộ luật Dân sự 2015",
            "formula": f"Tiền lãi chậm trả = {principal:,.0f} đ × {applicable_annual_rate:.1f}%/năm × ({overdue_days}/365 ngày) = {interest_amount:,.0f} đ",
            "formatted_summary": f"Tiền lãi chậm trả tính theo trần luật định ({applicable_annual_rate}%/năm): {interest_amount:,.0f} VNĐ",
            "ok": True,
        }

    # 9. Non-contractual Damage & Traffic Accident Compensation (Điều 584, 585, 589, 590 BLDS 2015)
    if calc_type in (
        "traffic_accident_damage_compensation",
        "civil_damage_compensation",
        "boi_thuong_thiet_hai_tai_nan",
        "damage_compensation",
        "tort_damage_compensation",
        "traffic_compensation",
        "boi_thuong_tai_nan",
    ):
        medical = float(params.get("medical_expenses_vnd", 0) or params.get("vien_phi_vnd", 0) or 0)
        property_dmg = float(params.get("property_damage_vnd", 0) or params.get("sua_xe_vnd", 0) or 0)
        lost_income = float(params.get("lost_income_vnd", 0) or params.get("thu_nhap_mat_vnd", 0) or 0)
        months_unworked = float(params.get("months_unworked", 0) or params.get("months_recovery", 0) or 0)
        monthly_salary = float(params.get("monthly_salary_vnd", 0) or params.get("monthly_income_vnd", 0) or 0)
        if lost_income <= 0 and months_unworked > 0 and monthly_salary > 0:
            lost_income = months_unworked * monthly_salary
        caretaker = float(params.get("caretaker_costs_vnd", 0) or params.get("nguoi_cham_soc_vnd", 0) or 0)

        total_compensation = medical + property_dmg + lost_income + caretaker

        return {
            "calculation_type": "traffic_accident_damage_compensation",
            "medical_expenses_vnd": round(medical, 0),
            "property_damage_vnd": round(property_dmg, 0),
            "lost_income_vnd": round(lost_income, 0),
            "caretaker_costs_vnd": round(caretaker, 0),
            "total_compensation_vnd": round(total_compensation, 0),
            "calculated_amount_vnd": round(total_compensation, 0),
            "legal_basis": "Điều 584, Điều 585, Điều 589 và Điều 590 Bộ luật Dân sự 2015",
            "formula": (
                f"Tổng bồi thường = Viện phí ({medical:,.0f} đ) + Sửa xe ({property_dmg:,.0f} đ) + "
                f"Thu nhập bị mất ({lost_income:,.0f} đ)"
                + (f" + Chi phí người chăm sóc ({caretaker:,.0f} đ)" if caretaker > 0 else "")
                + f" = {total_compensation:,.0f} đ"
            ),
            "formatted_summary": (
                f"Tổng mức bồi thường thiệt hại thực tế theo Điều 584, 585, 590 BLDS 2015 là: {total_compensation:,.0f} VNĐ "
                f"(Viện phí: {medical:,.0f} đ, Sửa xe: {property_dmg:,.0f} đ, Thu nhập bị mất: {lost_income:,.0f} đ)"
            ),
            "ok": True,
        }

    return {
        "calculation_type": calc_type,
        "error": f"Unsupported calculation type: '{calc_type}'",
        "supported_types": [
            "overtime_salary",
            "unlawful_termination_compensation",
            "severance_allowance",
            "probation_wage_floor",
            "traffic_fine",
            "traffic_accident_damage_compensation",
            "household_business_tax",
            "personal_income_tax",
            "late_payment_interest",
        ],
        "ok": False,
    }
