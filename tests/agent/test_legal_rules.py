"""Unit tests for Universal Multi-Domain Legal Rules & Calculation Engine."""

from __future__ import annotations

from epr_agent.domain.legal_rules import (
    LegalDomain,
    UniversalCaseFormResolver,
    calculate_legal_formula,
    evaluate_universal_case,
)


def test_labor_unlawful_termination_evaluation() -> None:
    """Test labor unlawful termination liability under Articles 36 and 41 BLLĐ."""
    res = evaluate_universal_case(
        legal_domain=LegalDomain.LABOR.value,
        facts={
            "dispute_type": "đơn phương chấm dứt hợp đồng lao động",
            "monthly_salary_vnd": "15000000",
            "termination_reason": "công ty muốn thay thế nhân sự mới",
            "notice_days_given": "5",
        },
    )
    assert res["ok"] is True
    assert res["status"] == "unlawful_termination"
    assert "TRÁI PHÁP LUẬT" in res["conclusion"]
    assert "Điều 41 Bộ luật Lao động 2019" in res["applicable_provisions"]
    assert res["financial_calculation"]["statutory_min_compensation_vnd"] == 30_000_000


def test_civil_contract_rental_increase_evaluation() -> None:
    """Test unilateral rent increase illegality under Article 478 BLDS."""
    res = evaluate_universal_case(
        legal_domain=LegalDomain.CIVIL_CONTRACT.value,
        facts={
            "contract_kind": "thuê nhà trọ",
            "dispute_issue": "chủ nhà tự ý tăng giá thuê nhà giữa chừng",
            "agreed_in_contract": "không",
            "notice_period_days": "0",
        },
    )
    assert res["ok"] is True
    assert res["status"] == "unlawful_price_increase"
    assert "KHÔNG ĐƯỢC TỰ Ý TĂNG GIÁ" in res["conclusion"]
    assert "Điều 478 Bộ luật Dân sự 2015" in res["applicable_provisions"]


def test_marriage_family_unilateral_divorce_evaluation() -> None:
    """Test unilateral divorce grounds under Article 56 HN&GĐ."""
    res = evaluate_universal_case(
        legal_domain=LegalDomain.MARRIAGE_FAMILY.value,
        facts={
            "divorce_type": "đơn phương",
            "divorce_grounds": "bạo lực gia đình và không thể tiếp tục chung sống",
            "marriage_certificate_status": "bị chồng giữ",
        },
    )
    assert res["ok"] is True
    assert res["status"] == "unilateral_divorce_eligible"
    assert "CÓ ĐỦ ĐIỀU KIỆN" in res["conclusion"]
    assert any("trích lục" in s for s in res["next_steps"])


def test_corporate_shareholder_threshold_evaluation() -> None:
    """Test 5% minority shareholder threshold under Article 115 LDN 2020."""
    # Met threshold
    res_met = evaluate_universal_case(
        legal_domain=LegalDomain.CORPORATE.value,
        facts={"shareholder_ratio_percent": "7.5"},
    )
    assert res_met["status"] == "threshold_met"
    assert "ĐỦ ĐIỀU KIỆN" in res_met["conclusion"]
    assert "Điều 115 Luật Doanh nghiệp 2020" in res_met["applicable_provisions"]

    # Not met
    res_unmet = evaluate_universal_case(
        legal_domain=LegalDomain.CORPORATE.value,
        facts={"shareholder_ratio_percent": "3.0"},
    )
    assert res_unmet["status"] == "threshold_not_met"


def test_traffic_fine_evaluation() -> None:
    """Test traffic fine evaluation under Decree 100/123."""
    res_bike = evaluate_universal_case(
        legal_domain=LegalDomain.TRAFFIC.value,
        facts={"vehicle_type": "xe máy", "violation_act": "vượt đèn đỏ"},
    )
    assert res_bike["status"] == "traffic_penalty_evaluated"
    assert res_bike["financial_calculation"]["min_fine_vnd"] == 800_000
    assert res_bike["financial_calculation"]["max_fine_vnd"] == 1_000_000


def test_statutory_calculations() -> None:
    """Test overtime salary and severance formula calculations."""
    # 1. Overtime Pay: Sunday (200%)
    ot_res = calculate_legal_formula(
        calculation_type="overtime_salary",
        parameters={"hourly_wage_vnd": 50000, "overtime_hours": 8, "day_type": "chủ nhật"},
    )
    assert ot_res["ok"] is True
    assert ot_res["statutory_rate_percent"] == 200
    assert ot_res["total_overtime_pay_vnd"] == 800_000  # 50,000 * 8 * 2.0

    # 2. Overtime Pay: Holiday (300%)
    holiday_res = calculate_legal_formula(
        calculation_type="overtime_salary",
        parameters={"hourly_wage_vnd": 50000, "overtime_hours": 4, "day_type": "ngày tết"},
    )
    assert holiday_res["statutory_rate_percent"] == 300
    assert holiday_res["total_overtime_pay_vnd"] == 600_000  # 50,000 * 4 * 3.0

    # 3. Unlawful termination indemnity: 2 months + 1 month unworked
    term_res = calculate_legal_formula(
        calculation_type="unlawful_termination_compensation",
        parameters={"monthly_salary_vnd": 20000000, "months_unworked": 1.5},
    )
    assert term_res["ok"] is True
    assert term_res["statutory_min_indemnity_vnd"] == 40_000_000
    assert term_res["total_minimum_compensation_vnd"] == 70_000_000  # (2 * 20M) + (1.5 * 20M)

    # 4. Severance allowance
    sev_res = calculate_legal_formula(
        calculation_type="severance_allowance",
        parameters={"monthly_salary_average_6m_vnd": 12000000, "qualifying_working_years": 4},
    )
    assert sev_res["ok"] is True
    assert sev_res["total_severance_vnd"] == 24_000_000  # 12M * 4 * 0.5


def test_universal_form_resolver() -> None:
    """Test dynamic slot resolution for labor and civil domains."""
    resolver = UniversalCaseFormResolver()

    # Incomplete labor form
    form_labor = resolver.resolve_form_state(
        legal_domain="labor",
        known_facts={"monthly_salary_vnd": "10000000"},
    )
    assert form_labor["status"] == "incomplete"
    assert "dispute_type" in form_labor["missing_facts"]
    assert "Để trợ lý pháp luật có thể tư vấn" in form_labor["suggested_follow_up"]

    # Complete labor form
    form_labor_complete = resolver.resolve_form_state(
        legal_domain="labor",
        known_facts={"dispute_type": "đơn phương sa thải"},
    )
    assert form_labor_complete["status"] == "complete"
    assert len(form_labor_complete["missing_facts"]) == 0
