import pytest
from epr_agent.tools.legal_calculators import (
    calculate_court_fees,
    calculate_illegal_termination_compensation,
    calculate_land_transfer_taxes,
    calculate_overdue_interest,
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
