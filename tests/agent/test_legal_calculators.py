from vietnam_legal_agent.tools.legal_calculators import (
    calculate_court_fees,
    calculate_illegal_termination_compensation,
    calculate_land_transfer_taxes,
    calculate_overdue_interest,
    calculate_severance_allowance,
)


def test_court_fees_non_monetary():
    res = calculate_court_fees(claim_amount=0, has_monetary_value=False)
    assert res.has_monetary_value is False
    assert res.first_instance_fee == 300000.0
    assert res.advance_fee == 150000.0


def test_court_fees_brackets():
    # 500 million VND claim
    # Bracket: 400M to 800M = 20M + 4% of 100M = 20M + 4M = 24M
    res = calculate_court_fees(claim_amount=500000000)
    assert res.has_monetary_value is True
    assert res.first_instance_fee == 24000000.0
    assert res.advance_fee == 12000000.0


def test_court_fees_commercial():
    # Commercial claim 100 million VND: 5% * 100M = 5M
    res = calculate_court_fees(claim_amount=100000000, dispute_type="kinh doanh thương mại")
    assert res.first_instance_fee == 5000000.0


def test_illegal_termination_compensation():
    # Salary 20 million, worked 12 months, 2 months unemployed, 30 days without notice
    res = calculate_illegal_termination_compensation(
        monthly_salary=20000000,
        months_worked=12,
        unemployed_months=2,
        days_without_notice=30,
    )
    assert res.minimum_compensation == 40000000.0  # 2 months salary
    assert res.unemployed_days_salary == 40000000.0  # 2 months unemployed pay
    assert res.salary_for_unnotified_days > 0
    assert res.total_compensation > 80000000.0
    assert len(res.actionable_notes) > 0


def test_overdue_interest_statutory_cap():
    # Agreed rate 30% -> must be capped at 20%
    res = calculate_overdue_interest(
        principal_amount=100000000,
        days_overdue=365,
        agreed_annual_rate=30.0,
    )
    assert res.is_capped_by_law is True
    assert res.applied_annual_rate == 20.0
    assert abs(res.total_interest - 20000000.0) < 1000.0
    assert res.warning_note is not None


def test_land_transfer_taxes():
    # 2 billion property
    res = calculate_land_transfer_taxes(property_value=2000000000)
    assert res.personal_income_tax == 40000000.0  # 2%
    assert res.registration_fee == 10000000.0  # 0.5%
    assert res.total_taxes_and_fees > 50000000.0

    # Family transfer
    res_family = calculate_land_transfer_taxes(property_value=2000000000, is_direct_family_transfer=True)
    assert res_family.personal_income_tax == 0.0
    assert res_family.registration_fee == 0.0


def test_court_fees_commercial_ten_billion():
    """Resolution 326/2016/UBTVQH14: Commercial claim > 4B applies 144M + 0.1% of excess.

    For 10 billion VND claim: 144,000,000 + 6,000,000,000 * 0.001 = 150,000,000 VND.
    """
    res = calculate_court_fees(
        claim_amount=10_000_000_000,
        dispute_type="kinh doanh thương mại",
        has_monetary_value=True,
    )
    assert res.first_instance_fee == 150_000_000.0
    assert res.advance_fee == 75_000_000.0
    assert res.appellate_fee == 2_000_000.0
    assert "0.1%" in res.breakdown_formula
    assert "144.000.000" in res.breakdown_formula


def test_court_fees_appellate_fee_by_dispute_type():
    """Commercial appellate fee is 2,000,000 VND; civil appellate fee is 300,000 VND."""
    # Non-monetary commercial
    res_non_monetary_comm = calculate_court_fees(
        claim_amount=0,
        dispute_type="kinh doanh thương mại",
        has_monetary_value=False,
    )
    assert res_non_monetary_comm.first_instance_fee == 3_000_000.0
    assert res_non_monetary_comm.appellate_fee == 2_000_000.0

    # Monetary commercial
    res_monetary_comm = calculate_court_fees(
        claim_amount=500_000_000,
        dispute_type="kinh doanh, thương mại",
        has_monetary_value=True,
    )
    assert res_monetary_comm.appellate_fee == 2_000_000.0

    # Non-monetary civil
    res_non_monetary_civ = calculate_court_fees(
        claim_amount=0,
        dispute_type="dân sự",
        has_monetary_value=False,
    )
    assert res_non_monetary_civ.first_instance_fee == 300_000.0
    assert res_non_monetary_civ.appellate_fee == 300_000.0

    # Monetary civil
    res_monetary_civ = calculate_court_fees(
        claim_amount=500_000_000,
        dispute_type="dân sự",
        has_monetary_value=True,
    )
    assert res_monetary_civ.appellate_fee == 300_000.0


def test_overdue_interest_commercial_uncapped():
    """Article 306 Commercial Law 2005 & Resolution 01/2019/NQ-HDTP: commercial interest is not capped at 20%."""
    # Commercial rate 25% (> 20%)
    res_25 = calculate_overdue_interest(
        principal_amount=100_000_000,
        days_overdue=365,
        agreed_annual_rate=25.0,
        is_commercial_contract=True,
    )
    assert res_25.is_capped_by_law is False
    assert res_25.applied_annual_rate == 25.0
    assert abs(res_25.total_interest - 25_000_000.0) < 1000.0
    assert res_25.warning_note is None
    assert "Điều 306 Luật Thương mại 2005" in res_25.legal_basis
    assert "Nghị quyết 01/2019/NQ-HĐTP" in res_25.legal_basis

    # Commercial rate 30% with is_commercial keyword alias
    res_30 = calculate_overdue_interest(
        principal_amount=100_000_000,
        days_overdue=365,
        agreed_annual_rate=30.0,
        is_commercial=True,
    )
    assert res_30.is_capped_by_law is False
    assert res_30.applied_annual_rate == 30.0
    assert abs(res_30.total_interest - 30_000_000.0) < 1000.0
    assert res_30.warning_note is None

    # Civil rate 30% remains capped at 20%
    res_civil = calculate_overdue_interest(
        principal_amount=100_000_000,
        days_overdue=365,
        agreed_annual_rate=30.0,
        is_commercial_contract=False,
    )
    assert res_civil.is_capped_by_law is True
    assert res_civil.applied_annual_rate == 20.0
    assert res_civil.warning_note is not None


def test_severance_allowance_minimum_service_requirement():
    """Article 46 Labor Code 2019: minimum 12 months service required; < 12 months yields 0 VND."""
    # 6 months worked without unemployment insurance
    res_6m = calculate_illegal_termination_compensation(
        monthly_salary=10_000_000,
        months_worked=6,
        has_unemployment_insurance=False,
    )
    assert res_6m.severance_allowance == 0.0

    # 11 months worked
    res_11m = calculate_illegal_termination_compensation(
        monthly_salary=10_000_000,
        months_worked=11,
        has_unemployment_insurance=False,
    )
    assert res_11m.severance_allowance == 0.0

    # Dedicated severance helper
    sev_6m = calculate_severance_allowance(monthly_salary=10_000_000, months_worked=6)
    assert sev_6m.qualifying_years == 0.0
    assert sev_6m.severance_allowance == 0.0
    assert "chưa đủ điều kiện" in sev_6m.breakdown_formula


def test_severance_allowance_statutory_month_rounding_decree_145():
    """Decree 145/2020/ND-CP Article 8: 1-6 odd months round to 0.5 year; > 6 odd months round to 1.0 year."""
    salary = 10_000_000.0

    # 14 months worked (1 year + 2 months): 2 <= 6 -> 1.5 qualifying years -> 1.5 * 0.5 * 10M = 7.5M
    res_14m = calculate_illegal_termination_compensation(
        monthly_salary=salary,
        months_worked=14,
        has_unemployment_insurance=False,
    )
    assert res_14m.severance_allowance == 7_500_000.0

    sev_14m = calculate_severance_allowance(monthly_salary=salary, months_worked=14)
    assert sev_14m.qualifying_years == 1.5
    assert sev_14m.severance_allowance == 7_500_000.0

    # 18 months worked (1 year + 6 months): 6 <= 6 -> 1.5 qualifying years -> 7.5M
    sev_18m = calculate_severance_allowance(monthly_salary=salary, months_worked=18)
    assert sev_18m.qualifying_years == 1.5
    assert sev_18m.severance_allowance == 7_500_000.0

    # 19 months worked (1 year + 7 months): 7 > 6 -> 2.0 qualifying years -> 2.0 * 0.5 * 10M = 10.0M
    sev_19m = calculate_severance_allowance(monthly_salary=salary, months_worked=19)
    assert sev_19m.qualifying_years == 2.0
    assert sev_19m.severance_allowance == 10_000_000.0

    # Exactly 12 months worked: 1.0 qualifying year -> 1.0 * 0.5 * 10M = 5.0M
    sev_12m = calculate_severance_allowance(monthly_salary=salary, months_worked=12)
    assert sev_12m.qualifying_years == 1.0
    assert sev_12m.severance_allowance == 5_000_000.0
