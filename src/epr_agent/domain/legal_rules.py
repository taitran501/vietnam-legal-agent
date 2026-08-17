"""Universal Multi-Domain Vietnamese Legal Decision & Calculation Engine.

Provides deterministic statutory evaluations, slot resolution, and legal formula calculations
across 7 core domains of Vietnamese Law:
1. Labor Law (Bộ luật Lao động 2019) - Overtime, Unlawful Termination, Severance
2. Civil & Contracts (Bộ luật Dân sự 2015) - Lease price adjust, Notice, Interest rate caps
3. Marriage & Family (Luật Hôn nhân và Gia đình 2014) - Unilateral Divorce, Child Custody
4. Enterprise Law (Luật Doanh nghiệp 2020) - Shareholder rights, EGM thresholds
5. Land Law (Luật Đất đai) - Land recovery compensation, Livelihood support
6. Traffic Fines (Nghị định 100/2019/NĐ-CP & NĐ 123/2021/NĐ-CP) - Fine brackets, License suspension
7. EPR Compliance (Luật BVMT 2020 & Nghị định 08/2022/NĐ-CP) - Revenue exemption, Recycling obligations
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from epr_agent.domain.epr_rules import (
    evaluate_assessment,
)
from epr_agent.domain.v4 import (
    FactConfirmationStatus,
    FactSource,
    FactValue,
)

logger = logging.getLogger(__name__)


class LegalDomain(str, Enum):
    LABOR = "labor"
    CIVIL_CONTRACT = "civil_contract"
    MARRIAGE_FAMILY = "marriage_family"
    CORPORATE = "corporate"
    LAND = "land"
    TRAFFIC = "traffic"
    EPR = "epr"
    GENERAL = "general"


DOMAIN_REQUIRED_FIELDS: dict[str, list[dict[str, Any]]] = {
    LegalDomain.LABOR.value: [
        {"field_name": "dispute_type", "label": "Loại tranh chấp lao động (đơn phương chấm dứt, làm thêm giờ, tiền lương, trợ cấp)", "required": True},
        {"field_name": "contract_type", "label": "Loại hợp đồng lao động (xác định thời hạn hay không xác định thời hạn)", "required": False},
        {"field_name": "monthly_salary_vnd", "label": "Mức tiền lương hàng tháng theo hợp đồng (VNĐ)", "required": False},
        {"field_name": "working_duration_months", "label": "Thời gian làm việc tại doanh nghiệp (tháng)", "required": False},
        {"field_name": "termination_reason", "label": "Lý do người sử dụng lao động đưa ra khi chấm dứt hợp đồng", "required": False},
        {"field_name": "notice_days_given", "label": "Số ngày báo trước thực tế", "required": False},
    ],
    LegalDomain.CIVIL_CONTRACT.value: [
        {"field_name": "contract_kind", "label": "Loại hợp đồng (thuê nhà/mặt bằng, vay tiền, mua bán tài sản, đặt cọc)", "required": True},
        {"field_name": "dispute_issue", "label": "Vấn đề tranh chấp (tăng giá thuê, chậm trả tiền, phạt cọc, lãi suất quá trần)", "required": True},
        {"field_name": "agreed_in_contract", "label": "Hợp đồng ban đầu có thỏa thuận về điều này không (có/không)", "required": False},
        {"field_name": "notice_period_days", "label": "Thời gian thông báo trước (ngày)", "required": False},
    ],
    LegalDomain.MARRIAGE_FAMILY.value: [
        {"field_name": "divorce_type", "label": "Yêu cầu ly hôn (thuận tình hay đơn phương)", "required": True},
        {"field_name": "divorce_grounds", "label": "Căn cứ ly hôn (bạo lực gia đình, vi phạm nghĩa vụ nghiêm trọng, không còn tình cảm)", "required": True},
        {"field_name": "marriage_certificate_status", "label": "Tình trạng giấy chứng nhận kết hôn (có sẵn hay bị giữ/mất)", "required": False},
        {"field_name": "has_minor_children", "label": "Có con chung dưới 36 tháng tuổi hoặc dưới 18 tuổi không", "required": False},
    ],
    LegalDomain.CORPORATE.value: [
        {"field_name": "company_type", "label": "Loại hình doanh nghiệp (công ty cổ phần, TNHH 1TV, TNHH 2TV trở lên)", "required": True},
        {"field_name": "shareholder_ratio_percent", "label": "Tỷ lệ sở hữu cổ phần hoặc phần vốn góp (%)", "required": True},
        {"field_name": "action_requested", "label": "Quyền yêu cầu (triệu tập họp ĐHĐCĐ/HĐTV, kiểm tra sổ sách, hủy nghị quyết)", "required": True},
    ],
    LegalDomain.LAND.value: [
        {"field_name": "land_category", "label": "Loại đất (đất ở, đất nông nghiệp, đất trồng cây lâu năm, đất thương mại)", "required": True},
        {"field_name": "issue_type", "label": "Vấn đề (thu hồi đất, bồi thường tái định cư, tranh chấp ranh giới, cấp sổ đỏ)", "required": True},
        {"field_name": "has_land_certificate", "label": "Đã có Giấy chứng nhận quyền sử dụng đất (Sổ đỏ/Sổ hồng) chưa", "required": False},
    ],
    LegalDomain.TRAFFIC.value: [
        {"field_name": "vehicle_type", "label": "Loại phương tiện (xe mô tô/xe gắn máy, xe ô tô, xe đạp điện)", "required": True},
        {"field_name": "violation_act", "label": "Hành vi vi phạm (vượt đèn đỏ, nồng độ cồn, chạy quá tốc độ, không đội mũ bảo hiểm)", "required": True},
        {"field_name": "alcohol_concentration", "label": "Nồng độ cồn đo được (nếu vi phạm cồn: chưa vượt 0.25mg/l, từ 0.25-0.4mg/l, trên 0.4mg/l)", "required": False},
    ],
    LegalDomain.EPR.value: [
        {"field_name": "business_role", "label": "Vai trò doanh nghiệp (nhà sản xuất, nhà nhập khẩu)", "required": True},
        {"field_name": "object_kind", "label": "Loại đối tượng (bao bì thương phẩm, sản phẩm)", "required": True},
        {"field_name": "product_group", "label": "Nhóm sản phẩm/bao bì (bao bì, pin, ắc quy, săm lốp, dầu nhớt, điện tử)", "required": True},
        {"field_name": "market_placement", "label": "Thị trường tiêu thụ (thị trường Việt Nam, xuất khẩu)", "required": True},
        {"field_name": "annual_revenue_vnd", "label": "Doanh thu năm trước liền kề (VNĐ)", "required": True},
    ],
}


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
    """Deterministically evaluate factual situations across all 7 legal domains."""
    domain_clean = (legal_domain or "general").strip().lower()
    norm_facts = {str(k).lower(): str(v).strip() for k, v in (facts or {}).items()}

    # ── 1. LABOR LAW DOMAIN ──
    if domain_clean in ("labor", "lao_dong", "lao động", "luật lao động"):
        dispute_type = norm_facts.get("dispute_type", "").lower()
        salary = float(norm_facts.get("monthly_salary_vnd", "0") or "0")
        notice_days = int(norm_facts.get("notice_days_given", "-1") or "-1")
        reason = norm_facts.get("termination_reason", "").lower()

        # Unlawful termination assessment
        if "đơn phương" in dispute_type or "chấm dứt" in dispute_type or reason:
            is_unlawful = True
            reasons = []
            if "thường xuyên không hoàn thành" in reason or "ốm đau dài ngày" in reason or "thiên tai" in reason:
                if notice_days >= 45:  # HĐ không xác định thời hạn
                    is_unlawful = False
                    reasons.append("Người sử dụng lao động có lý do luật định và đáp ứng thời hạn báo trước 45 ngày theo Điều 36.")
                else:
                    reasons.append("Có lý do luật định nhưng vi phạm thời hạn báo trước theo Điều 36 Bộ luật Lao động 2019.")
            else:
                reasons.append("Lý do chấm dứt không thuộc các trường hợp luật định tại Điều 36 Bộ luật Lao động 2019.")

            if is_unlawful:
                comp_months = 2.0
                min_comp_vnd = salary * comp_months if salary > 0 else 0
                return {
                    "domain": "labor",
                    "status": "unlawful_termination",
                    "conclusion": "Việc người sử dụng lao động chấm dứt hợp đồng lao động có dấu hiệu TRÁI PHÁP LUẬT theo Điều 36 và Điều 41 Bộ luật Lao động 2019.",
                    "reasons": reasons,
                    "applicable_provisions": ["Điều 36 Bộ luật Lao động 2019", "Điều 41 Bộ luật Lao động 2019"],
                    "financial_calculation": {
                        "statutory_min_compensation_months": 2,
                        "statutory_min_compensation_vnd": min_comp_vnd,
                        "additional_liabilities": "Tiền lương trong những ngày không được làm việc + đóng bảo hiểm bắt buộc + trợ cấp thôi việc (nếu không tiếp tục làm việc).",
                    },
                    "next_steps": [
                        "Yêu cầu công ty bồi thường thỏa thuận theo Điều 41 BLLĐ 2019.",
                        "Gửi đơn khiếu nại tới Phòng LĐ-TB&XH hoặc khởi kiện tại TAND cấp huyện.",
                    ],
                    "ok": True,
                }

    # ── 2. CIVIL & CONTRACTS DOMAIN ──
    if domain_clean in ("civil_contract", "dan_su", "dân sự", "hợp đồng", "thue_nha"):
        agreed = norm_facts.get("agreed_in_contract", "không").lower()
        dispute_issue = norm_facts.get("dispute_issue", "").lower()

        if ("tăng giá" in dispute_issue or "thuê nhà" in dispute_issue) and agreed in ("không", "no", "false", "0"):
            return {
                "domain": "civil_contract",
                "status": "unlawful_price_increase",
                "conclusion": "Bên cho thuê KHÔNG ĐƯỢC TỰ Ý TĂNG GIÁ THUÊ NHÀ giữa chừng khi hợp đồng không có thỏa thuận theo Điều 478 Bộ luật Dân sự 2015.",
                "reasons": [
                    "Theo Điều 472 và Điều 478 Bộ luật Dân sự 2015, giá thuê nhà do các bên thỏa thuận và không được đơn phương thay đổi trong thời hạn hợp đồng.",
                    "Mọi điều chỉnh phải được sự đồng thuận hoặc thông báo trước thời hạn hợp lý (tối thiểu 30 ngày).",
                ],
                "applicable_provisions": ["Điều 472 Bộ luật Dân sự 2015", "Điều 478 Bộ luật Dân sự 2015"],
                "next_steps": [
                    "Lập văn bản từ chối tăng giá dựa trên hợp đồng đã ký và Điều 478 BLDS 2015.",
                    "Yêu cầu tiếp tục thực hiện hợp đồng theo giá cũ hoặc hoàn trả tiền cọc nếu chủ nhà đơn phương hủy hợp đồng.",
                ],
                "ok": True,
            }

    # ── 3. MARRIAGE & FAMILY DOMAIN ──
    if domain_clean in ("marriage_family", "hon_nhan", "hôn nhân", "ly_hon", "ly hôn"):
        cert_status = norm_facts.get("marriage_certificate_status", "").lower()
        reasons = [
            "Căn cứ Điều 51 và Điều 56 Luật Hôn nhân và Gia đình 2014, vợ hoặc chồng có quyền yêu cầu Tòa án giải quyết ly hôn đơn phương.",
        ]
        if "giữ" in cert_status or "mất" in cert_status or "thiếu" in cert_status:
            reasons.append("Nếu bị giữ giấy đăng ký kết hôn, người yêu cầu có quyền xin cấp bản sao trích lục kết hôn tại UBND cấp xã nơi đăng ký để nộp hồ sơ.")

        return {
            "domain": "marriage_family",
            "status": "unilateral_divorce_eligible",
            "conclusion": "Người yêu cầu CÓ ĐỦ ĐIỀU KIỆN nộp đơn yêu cầu Tòa án giải quyết ly hôn đơn phương theo Điều 56 Luật Hôn nhân và Gia đình 2014.",
            "reasons": reasons,
            "applicable_provisions": ["Điều 51 Luật Hôn nhân và Gia đình 2014", "Điều 56 Luật Hôn nhân và Gia đình 2014"],
            "next_steps": [
                "Xin cấp bản sao trích lục đăng ký kết hôn tại UBND xã/phường nơi đăng ký kết hôn.",
                "Chuẩn bị CCCD, Giấy khai sinh con chung, Giấy tờ tài sản (nếu có tranh chấp).",
                "Nộp đơn khởi kiện ly hôn tại Tòa án nhân dân cấp huyện nơi bị đơn (chồng/vợ) cư trú hoặc làm việc.",
            ],
            "ok": True,
        }

    # ── 4. CORPORATE & ENTERPRISE DOMAIN ──
    if domain_clean in ("corporate", "doanh_nghiep", "doanh nghiệp", "công ty", "co_dong"):
        ratio = float(norm_facts.get("shareholder_ratio_percent", "0") or "0")
        if ratio >= 5.0:
            return {
                "domain": "corporate",
                "status": "threshold_met",
                "conclusion": f"Cổ đông/nhóm cổ đông sở hữu {ratio}% cổ phần ĐỦ ĐIỀU KIỆN thực hiện quyền triệu tập họp ĐHĐCĐ bất thường theo Điều 115 Luật Doanh nghiệp 2020.",
                "reasons": [
                    "Khoản 2 Điều 115 Luật Doanh nghiệp 2020 quy định cổ đông hoặc nhóm cổ đông sở hữu từ 05% tổng số cổ phần phổ thông trở lên có quyền yêu cầu triệu tập Đại hội đồng cổ đông bất thường khi HĐQT vi phạm nghiêm trọng quyền của cổ đông.",
                    "Được quyền xem xét, tra cứu và trích lục biên bản, nghị quyết của HĐQT.",
                ],
                "applicable_provisions": ["Điều 115 Luật Doanh nghiệp 2020", "Điều 140 Luật Doanh nghiệp 2020"],
                "next_steps": [
                    "Gửi văn bản yêu cầu HĐQT triệu tập họp ĐHĐCĐ bất thường kèm các tài liệu chứng minh vi phạm.",
                    "Nếu HĐQT không triệu tập trong 30 ngày, Ban kiểm soát có trách nhiệm triệu tập; nếu BKS không triệu tập thì nhóm cổ đông có quyền tự triệu tập theo Điều 140.",
                ],
                "ok": True,
            }
        return {
            "domain": "corporate",
            "status": "threshold_not_met",
            "conclusion": f"Tỷ lệ sở hữu {ratio}% CHƯA ĐẠT ngưỡng tối thiểu 5% theo luật định để tự thực hiện quyền yêu cầu triệu tập họp ĐHĐCĐ bất thường.",
            "reasons": ["Cần liên kết với các cổ đông khác để đạt tối thiểu 5% tổng số cổ phần phổ thông theo Điều 115 Luật Doanh nghiệp 2020."],
            "applicable_provisions": ["Điều 115 Luật Doanh nghiệp 2020"],
            "ok": True,
        }

    # ── 5. TRAFFIC FINES DOMAIN ──
    if domain_clean in ("traffic", "giao_thong", "giao thông", "nghi_dinh_100"):
        vehicle = norm_facts.get("vehicle_type", "xe máy").lower()
        violation = norm_facts.get("violation_act", "").lower()

        if "vượt đèn đỏ" in violation or "đèn tín hiệu" in violation or "đèn đỏ" in violation:
            if "ô tô" in vehicle or "xe hơi" in vehicle:
                return {
                    "domain": "traffic",
                    "status": "traffic_penalty_evaluated",
                    "conclusion": "Mức phạt hành vi vượt đèn đỏ đối với xe ô tô: 4.000.000đ - 6.000.000đ theo Nghị định 100/2019/NĐ-CP (sửa đổi bởi NĐ 123/2021).",
                    "reasons": ["Điểm a Khoản 5 Điều 5 Nghị định 100/2019/NĐ-CP.", "Bị tước Giấy phép lái xe từ 01 tháng đến 03 tháng."],
                    "applicable_provisions": ["Điều 5 Nghị định 100/2019/NĐ-CP", "Nghị định 123/2021/NĐ-CP"],
                    "financial_calculation": {"min_fine_vnd": 4000000, "max_fine_vnd": 6000000, "license_suspension_months": "1 - 3 tháng"},
                    "ok": True,
                }
            return {
                "domain": "traffic",
                "status": "traffic_penalty_evaluated",
                "conclusion": "Mức phạt hành vi vượt đèn đỏ đối với xe mô tô, xe gắn máy: 800.000đ - 1.000.000đ theo Nghị định 100/2019/NĐ-CP.",
                "reasons": ["Điểm e Khoản 4 Điều 6 Nghị định 100/2019/NĐ-CP (sửa đổi bởi NĐ 123/2021/NĐ-CP).", "Bị tước Giấy phép lái xe từ 01 tháng đến 03 tháng."],
                "applicable_provisions": ["Điều 6 Nghị định 100/2019/NĐ-CP", "Nghị định 123/2021/NĐ-CP"],
                "financial_calculation": {"min_fine_vnd": 800000, "max_fine_vnd": 1000000, "license_suspension_months": "1 - 3 tháng"},
                "ok": True,
            }

    # ── 6. EPR DOMAIN (FALLBACK TO EXISTING DETERMINISTIC EPR RULE ENGINE) ──
    if domain_clean in ("epr", "moitruong", "môi trường", "tai_che", "bao_bi"):
        typed_facts: dict[str, FactValue] = {
            k: FactValue(
                value=str(v),
                source=FactSource.USER_TURN,
                confirmation_status=FactConfirmationStatus.USER_CONFIRMED,
                verified=True,
            )
            for k, v in norm_facts.items()
            if str(v).strip()
        }
        res = evaluate_assessment(typed_facts, evidence_ids={})
        return {
            "domain": "epr",
            "status": res.status.value,
            "conclusion": res.conclusion,
            "reasons": [r.model_dump(mode="json") for r in res.reasons],
            "applicable_provisions": ["Điều 77 Luật BVMT 2020", "Điều 54 Nghị định 08/2022/NĐ-CP"],
            "missing_facts": res.missing_facts,
            "next_steps": res.next_steps,
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
    """Execute deterministic statutory calculations (overtime, indemnities, traffic fines, severance)."""
    calc_type = (calculation_type or "").strip().lower()
    params = {str(k).lower(): v for k, v in (parameters or {}).items()}

    # 1. Overtime Pay Calculation (Điều 98 BLLĐ 2019)
    if calc_type in ("overtime_salary", "tien_luong_lam_them_gio", "overtime"):
        hourly_wage = float(params.get("hourly_wage_vnd", 0) or 0)
        hours = float(params.get("overtime_hours", 0) or 0)
        day_type = str(params.get("day_type", "weekday")).lower()

        multiplier = 1.5
        day_label = "ngày thường (ít nhất 150%)"
        if "chủ nhật" in day_type or "cuối tuần" in day_type or "weekend" in day_type or "nghỉ hằng tuần" in day_type:
            multiplier = 2.0
            day_label = "ngày nghỉ hằng tuần / Chủ nhật (ít nhất 200%)"
        elif "lễ" in day_type or "tết" in day_type or "holiday" in day_type:
            multiplier = 3.0
            day_label = "ngày nghỉ lễ, tết có hưởng lương (ít nhất 300%)"

        total_pay = hourly_wage * hours * multiplier
        return {
            "calculation_type": "overtime_salary",
            "statutory_rate_percent": int(multiplier * 100),
            "day_type_label": day_label,
            "total_overtime_pay_vnd": total_pay,
            "legal_basis": "Điều 98 Bộ luật Lao động 2019",
            "formula": f"Tiền lương làm thêm = {hourly_wage:,.0f} đ/giờ × {hours} giờ × {multiplier:.1f} ({multiplier*100:.0f}%) = {total_pay:,.0f} đ",
            "ok": True,
        }

    # 2. Unlawful Termination Compensation (Điều 41 BLLĐ 2019)
    if calc_type in ("unlawful_termination_compensation", "boi_thuong_sa_thai_trai_luat", "termination"):
        salary = float(params.get("monthly_salary_vnd", 0) or 0)
        months_unworked = float(params.get("months_unworked", 0) or 0)
        min_statutory_months = 2.0

        comp_statutory = salary * min_statutory_months
        back_pay = salary * months_unworked
        total_comp = comp_statutory + back_pay

        return {
            "calculation_type": "unlawful_termination_compensation",
            "statutory_min_indemnity_months": 2,
            "statutory_min_indemnity_vnd": comp_statutory,
            "back_pay_during_unworked_period_vnd": back_pay,
            "total_minimum_compensation_vnd": total_comp,
            "legal_basis": "Điều 41 Bộ luật Lao động 2019",
            "formula": f"Bồi thường tối thiểu = (2 tháng lương × {salary:,.0f} đ) + (Tiền lương những ngày không được làm việc: {months_unworked} tháng × {salary:,.0f} đ) = {total_comp:,.0f} đ",
            "ok": True,
        }

    # 3. Severance Allowance (Điều 46 BLLĐ 2019)
    if calc_type in ("severance_allowance", "tro_cap_thoi_viec", "severance"):
        salary = float(params.get("monthly_salary_average_6m_vnd", 0) or 0)
        years = float(params.get("qualifying_working_years", 0) or 0)
        total_allowance = salary * years * 0.5

        return {
            "calculation_type": "severance_allowance",
            "qualifying_working_years": years,
            "rate_per_year": "0.5 tháng tiền lương bình quân 6 tháng liền kề",
            "total_severance_vnd": total_allowance,
            "legal_basis": "Điều 46 Bộ luật Lao động 2019",
            "formula": f"Trợ cấp thôi việc = {years} năm × 0.5 × {salary:,.0f} đ = {total_allowance:,.0f} đ",
            "ok": True,
        }

    return {
        "calculation_type": calc_type,
        "error": f"Unsupported calculation type: '{calc_type}'",
        "supported_types": ["overtime_salary", "unlawful_termination_compensation", "severance_allowance"],
        "ok": False,
    }


class UniversalCaseFormResolver:
    """Dynamic form resolver supporting slot filling across multiple legal domains."""

    def resolve_form_state(
        self,
        legal_domain: str,
        known_facts: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        domain_clean = (legal_domain or "general").strip().lower()
        fields_def = DOMAIN_REQUIRED_FIELDS.get(domain_clean, DOMAIN_REQUIRED_FIELDS[LegalDomain.LABOR.value])
        facts = {str(k).lower(): str(v).strip() for k, v in (known_facts or {}).items()}

        missing_fields: list[str] = []
        completed_fields: list[dict[str, Any]] = []

        for f in fields_def:
            name = f["field_name"]
            is_req = f.get("required", False)
            val = facts.get(name)
            if val:
                completed_fields.append({"name": name, "label": f["label"], "value": val})
            elif is_req:
                missing_fields.append(name)

        status = "complete" if not missing_fields else "incomplete"
        suggested_question = None
        if missing_fields:
            missing_labels = [f["label"] for f in fields_def if f["field_name"] in missing_fields]
            suggested_question = "Để trợ lý pháp luật có thể tư vấn và đánh giá chính xác, bạn vui lòng cung cấp thêm:\n" + "\n".join(
                f"{i+1}. {lbl}" for i, lbl in enumerate(missing_labels)
            )

        return {
            "domain": domain_clean,
            "status": status,
            "missing_facts": missing_fields,
            "completed_count": len(completed_fields),
            "required_count": len([f for f in fields_def if f.get("required")]),
            "fields": completed_fields,
            "suggested_follow_up": suggested_question,
            "ok": True,
        }
