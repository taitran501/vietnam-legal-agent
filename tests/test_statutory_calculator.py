"""Unit tests for all Statutory Financial Calculations in Vietnamese Law."""

from __future__ import annotations

import pytest

from epr_agent.agent.tool_registry import calculate_statutory_amounts
from epr_agent.domain.legal_rules import calculate_legal_formula


def test_overtime_salary_calculation() -> None:
    """Test overtime salary on normal day (150%), weekend (200%), and holiday (300%)."""
    # Normal day
    res_normal = calculate_legal_formula(
        calculation_type="overtime_salary",
        parameters={"hourly_wage_vnd": 100_000, "overtime_hours": 3, "day_type": "ngày thường"},
    )
    assert res_normal["calculated_amount_vnd"] == 450_000
    assert res_normal["rate_multiplier"] == 1.5

    # Weekend (Sunday)
    res_weekend = calculate_legal_formula(
        calculation_type="overtime_salary",
        parameters={"hourly_wage_vnd": 100_000, "overtime_hours": 4, "day_type": "chủ nhật"},
    )
    assert res_weekend["calculated_amount_vnd"] == 800_000
    assert res_weekend["rate_multiplier"] == 2.0

    # Holiday (Tet / National Day)
    res_holiday = calculate_legal_formula(
        calculation_type="overtime_salary",
        parameters={"hourly_wage_vnd": 100_000, "overtime_hours": 8, "day_type": "lễ tết"},
    )
    assert res_holiday["calculated_amount_vnd"] == 2_400_000
    assert res_holiday["rate_multiplier"] == 3.0


def test_unlawful_termination_compensation() -> None:
    """Test compensation under Article 41 Labor Code 2019."""
    res = calculate_legal_formula(
        calculation_type="unlawful_termination_compensation",
        parameters={
            "monthly_salary_vnd": 20_000_000,
            "unworked_days_without_notice": 20,
            "months_awaiting_settlement": 3,
        },
    )
    # Min 2 months (40m) + 3 months awaiting (60m) + notice penalty (20 days ~ 15.38m)
    assert res["statutory_min_2_months_vnd"] == 40_000_000
    assert res["salary_during_awaiting_days_vnd"] == 60_000_000
    assert res["total_estimated_compensation_vnd"] > 100_000_000
    assert "Điều 41 Bộ luật Lao động 2019" in res["legal_basis"]


def test_severance_allowance() -> None:
    """Test severance allowance under Article 46 Labor Code 2019 (0.5 month per year)."""
    res = calculate_legal_formula(
        calculation_type="severance_allowance",
        parameters={"monthly_salary_vnd": 12_000_000, "years_of_service": 4.5},
    )
    assert res["calculated_amount_vnd"] == 27_000_000
    assert "Điều 46 Bộ luật Lao động 2019" in res["legal_basis"]


def test_probation_wage_floor() -> None:
    """Test probation wage minimum 85% under Article 26 Labor Code 2019."""
    res = calculate_legal_formula(
        calculation_type="probation_wage_floor",
        parameters={"official_monthly_salary_vnd": 10_000_000},
    )
    assert res["min_probation_salary_vnd"] == 8_500_000
    assert "Điều 26 Bộ luật Lao động 2019" in res["legal_basis"]


def test_traffic_fine_calculation() -> None:
    """Test Decree 100/123 traffic fines for alcohol violation."""
    res = calculate_legal_formula(
        calculation_type="traffic_fine",
        parameters={
            "vehicle_type": "xe máy",
            "violation_act": "nồng độ cồn",
            "alcohol_level": "level_3",
        },
    )
    assert res["min_fine_vnd"] == 6_000_000
    assert res["max_fine_vnd"] == 8_000_000
    assert res["midpoint_fine_vnd"] == 7_000_000
    assert "Nghị định 100/2019/NĐ-CP" in res["legal_basis"]


def test_household_business_tax_calculation() -> None:
    """Test presumptive tax calculation for household business (Circular 40/2021/TT-BTC)."""
    # Below 100m annual exemption threshold
    res_exempt = calculate_legal_formula(
        calculation_type="household_business_tax",
        parameters={"monthly_revenue_vnd": 5_000_000, "business_sector": "food_and_beverage"},
    )
    assert res_exempt["is_exempt"] is True
    assert res_exempt["total_monthly_tax_vnd"] == 0

    # Above 100m annual threshold: F&B (3% VAT + 1.5% PIT = 4.5%)
    res_taxable = calculate_legal_formula(
        calculation_type="household_business_tax",
        parameters={"monthly_revenue_vnd": 50_000_000, "business_sector": "food_and_beverage"},
    )
    assert res_taxable["is_exempt"] is False
    assert res_taxable["monthly_vat_vnd"] == 1_500_000  # 3%
    assert res_taxable["monthly_pit_vnd"] == 750_000   # 1.5%
    assert res_taxable["total_monthly_tax_vnd"] == 2_250_000  # 4.5%


def test_personal_income_tax_progressive_brackets() -> None:
    """Test 7-bracket progressive personal income tax (Circular 111/2013/TT-BTC)."""
    # 25m gross with 1 dependent -> taxable = 25 - 11 - 4.4 = 9.6m
    # Bracket 1 (0-5m @ 5% = 250k), Bracket 2 (5-9.6m @ 10% = 460k) -> total PIT = 710k
    res = calculate_legal_formula(
        calculation_type="personal_income_tax",
        parameters={"monthly_gross_salary_vnd": 25_000_000, "dependents_count": 1},
    )
    assert res["taxable_income_vnd"] == 9_600_000
    assert res["pit_tax_amount_vnd"] == 710_000


def test_late_payment_interest_statutory_cap() -> None:
    """Test civil interest capped at 20%/year under Article 468 Civil Code 2015."""
    # Principal 100m, 365 days, rate 30% (should cap at 20%)
    res = calculate_legal_formula(
        calculation_type="late_payment_interest",
        parameters={
            "principal_vnd": 100_000_000,
            "days_overdue": 365,
            "annual_interest_rate_percent": 30.0,
        },
    )
    assert res["applied_annual_rate_percent"] == 20.0
    assert res["was_capped_at_statutory_limit"] is True
    assert res["interest_amount_vnd"] == 20_000_000
    assert "Điều 468 Bộ luật Dân sự 2015" in res["legal_basis"]


@pytest.mark.asyncio
async def test_tool_calculate_statutory_amounts_integration() -> None:
    """Test calculate_statutory_amounts agent tool integration."""
    tool_res = await calculate_statutory_amounts(
        calculation_type="severance_allowance",
        parameters={"monthly_salary_vnd": 15000000, "years_of_service": 2},
    )
    assert tool_res["ok"] is True
    assert tool_res["calculated_amount_vnd"] == 15000000


def test_traffic_accident_damage_compensation() -> None:
    """Test non-contractual traffic damage calculation under Articles 584, 585, 590 Civil Code 2015."""
    res = calculate_legal_formula(
        calculation_type="traffic_accident_damage_compensation",
        parameters={
            "medical_expenses_vnd": 25_000_000,
            "property_damage_vnd": 5_000_000,
            "monthly_salary_vnd": 20_000_000,
            "months_unworked": 2,
        },
    )
    assert res["ok"] is True
    assert res["total_compensation_vnd"] == 70_000_000
    assert "Điều 584, Điều 585, Điều 589 và Điều 590 Bộ luật Dân sự 2015" in res["legal_basis"]
