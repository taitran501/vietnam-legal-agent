"""Empirical stress tests and boundary verification for Milestone M1 (Statutory Legal Calculations).

Adversarially validates:
1. Commercial Court Fees (Resolution 326/2016/UBTVQH14)
2. Overdue Interest Caps & Commercial Law (Art. 306 Commercial Law 2005 & Art. 468 Civil Code 2015)
3. Severance Allowance Eligibility & Rounding (Art. 46 Labor Code 2019 & Art. 8 Decree 145/2020/ND-CP)
"""

import pytest

from vietnam_legal_agent.domain.legal_rules import calculate_legal_formula
from vietnam_legal_agent.tools.legal_calculators import (
    calculate_court_fees,
    calculate_illegal_termination_compensation,
    calculate_overdue_interest,
    calculate_qualifying_working_years,
    calculate_severance_allowance,
)

# ==============================================================================
# SECTION 1: Commercial Court Fees Boundary & Stress Tests
# Resolution 326/2016/UBTVQH14 Part II (Danh muc an phi, le phi Toa an)
# ==============================================================================


class TestCommercialCourtFeesStress:
    """Stress tests for commercial court fee brackets and boundaries."""

    @pytest.mark.parametrize(
        "claim,expected_first_instance,expected_advance,expected_appellate,description",
        [
            # Boundary 1: 0 VND
            (0, 3_000_000.0, 1_500_000.0, 2_000_000.0, "Claim 0 VND treated as non-monetary commercial dispute"),
            # Bracket 1 boundary: <= 60M (flat 3M)
            (1, 3_000_000.0, 1_500_000.0, 2_000_000.0, "1 VND -> flat 3M"),
            (60_000_000, 3_000_000.0, 1_500_000.0, 2_000_000.0, "Exact 60M boundary -> flat 3M"),
            # Bracket 2: 60M < claim <= 400M (5%)
            (60_000_001, 3_000_000.05, 1_500_000.03, 2_000_000.0, "60M + 1 VND -> 5% = 3,000,000.05"),
            (100_000_000, 5_000_000.0, 2_500_000.0, 2_000_000.0, "100M -> 5% = 5M"),
            (400_000_000, 20_000_000.0, 10_000_000.0, 2_000_000.0, "Exact 400M boundary -> 5% = 20M"),
            # Bracket 3: 400M < claim <= 2B (20M + 4% of excess over 400M)
            (400_000_001, 20_000_000.04, 10_000_000.02, 2_000_000.0, "400M + 1 VND -> 20M + 0.04"),
            (1_000_000_000, 44_000_000.0, 22_000_000.0, 2_000_000.0, "1B -> 20M + 4% of 600M = 44M"),
            (2_000_000_000, 84_000_000.0, 42_000_000.0, 2_000_000.0, "Exact 2B boundary -> 20M + 4% of 1.6B = 84M"),
            # Bracket 4: 2B < claim <= 4B (84M + 3% of excess over 2B)
            (2_000_000_001, 84_000_000.03, 42_000_000.02, 2_000_000.0, "2B + 1 VND -> 84M + 0.03"),
            (3_000_000_000, 114_000_000.0, 57_000_000.0, 2_000_000.0, "3B -> 84M + 3% of 1B = 114M"),
            (4_000_000_000, 144_000_000.0, 72_000_000.0, 2_000_000.0, "Exact 4B boundary -> 84M + 3% of 2B = 144M"),
            # Bracket 5: > 4B (144M + 0.1% of excess over 4B)
            (4_000_000_001, 144_000_000.0, 72_000_000.0, 2_000_000.0, "4B + 1 VND -> 144M + 0.001 rounded to 2 decimals"),
            (5_000_000_000, 145_000_000.0, 72_500_000.0, 2_000_000.0, "5B -> 144M + 0.1% of 1B = 145M"),
            (10_000_000_000, 150_000_000.0, 75_000_000.0, 2_000_000.0, "10B -> 144M + 0.1% of 6B = 150M"),
            (100_000_000_000, 240_000_000.0, 120_000_000.0, 2_000_000.0, "100B -> 144M + 0.1% of 96B = 240M"),
            (1_000_000_000_000, 1_140_000_000.0, 570_000_000.0, 2_000_000.0, "1 Trillion VND -> 144M + 0.1% of 996B = 1.14B"),
        ],
    )
    def test_commercial_claim_boundaries(
        self, claim, expected_first_instance, expected_advance, expected_appellate, description
    ):
        res = calculate_court_fees(claim_amount=claim, dispute_type="kinh doanh thương mại")
        assert res.first_instance_fee == pytest.approx(expected_first_instance, abs=0.01), f"Failed for {description}: first instance"
        assert res.advance_fee == pytest.approx(expected_advance, abs=0.01), f"Failed for {description}: advance"
        assert res.appellate_fee == expected_appellate, f"Failed for {description}: appellate"

    def test_dispute_type_casing_and_variants(self):
        """Test robust handling of dispute_type strings."""
        variants = [
            "kinh doanh thương mại",
            "KINH DOANH THƯƠNG MẠI",
            "Kinh Doanh, Thương Mại",
            "Tranh chấp kinh doanh thương mại",
            "hợp đồng thương mại",
        ]
        for v in variants:
            res = calculate_court_fees(claim_amount=10_000_000_000, dispute_type=v)
            assert res.first_instance_fee == 150_000_000.0, f"Failed for variant '{v}'"
            assert res.appellate_fee == 2_000_000.0

    def test_civil_vs_commercial_distinct_brackets(self):
        """Ensure civil and commercial calculations do not cross-contaminate."""
        # At 10B VND:
        # Civil: 112M + 0.1% of 6B = 118M; appellate = 300k
        # Commercial: 144M + 0.1% of 6B = 150M; appellate = 2M
        res_civ = calculate_court_fees(claim_amount=10_000_000_000, dispute_type="dân sự")
        res_comm = calculate_court_fees(claim_amount=10_000_000_000, dispute_type="kinh doanh thương mại")

        assert res_civ.first_instance_fee == 118_000_000.0
        assert res_civ.appellate_fee == 300_000.0
        assert res_comm.first_instance_fee == 150_000_000.0
        assert res_comm.appellate_fee == 2_000_000.0
        assert res_comm.first_instance_fee != res_civ.first_instance_fee


# ==============================================================================
# SECTION 2: Commercial Overdue Interest Stress & Boundary Tests
# Art. 306 Commercial Law 2005 & Art. 468 Civil Code 2015 & Res 01/2019/NQ-HDTP
# ==============================================================================


class TestOverdueInterestStress:
    """Stress tests for interest rates across commercial and civil disputes."""

    @pytest.mark.parametrize(
        "rate,is_commercial,expected_applied_rate,expected_capped,expected_warning",
        [
            # Rate 0%
            (0.0, True, 0.0, False, None),
            (0.0, False, 0.0, False, None),
            # Rate 15%
            (15.0, True, 15.0, False, None),
            (15.0, False, 15.0, False, None),
            # Exact statutory civil boundary: 20%
            (20.0, True, 20.0, False, None),
            (20.0, False, 20.0, False, None),
            # Just above 20%: 20.01%
            (20.01, True, 20.01, False, None),
            (20.01, False, 20.0, True, "vượt trần"),
            # 25%
            (25.0, True, 25.0, False, None),
            (25.0, False, 20.0, True, "vượt trần"),
            # 35%
            (35.0, True, 35.0, False, None),
            (35.0, False, 20.0, True, "vượt trần"),
            # Extreme rate: 100%
            (100.0, True, 100.0, False, None),
            (100.0, False, 20.0, True, "vượt trần"),
        ],
    )
    def test_calculator_interest_rates(
        self, rate, is_commercial, expected_applied_rate, expected_capped, expected_warning
    ):
        principal = 100_000_000.0
        days = 365
        res = calculate_overdue_interest(
            principal_amount=principal,
            days_overdue=days,
            agreed_annual_rate=rate,
            is_commercial_contract=is_commercial,
        )
        assert res.applied_annual_rate == pytest.approx(expected_applied_rate, abs=0.001)
        assert res.is_capped_by_law is expected_capped
        if expected_warning:
            assert res.warning_note is not None
            assert expected_warning in res.warning_note
        else:
            assert res.warning_note is None

        # Verify math: P * r / 365 * days
        expected_interest = (principal * (expected_applied_rate / 100.0) / 365.0) * days
        assert res.total_interest == pytest.approx(expected_interest, abs=1.0)
        assert res.total_payable == pytest.approx(principal + expected_interest, abs=1.0)

    @pytest.mark.parametrize(
        "rate,is_commercial,expected_applied_rate,expected_capped,expected_usury",
        [
            (15.0, True, 15.0, False, False),
            (15.0, False, 15.0, False, False),
            (20.0, True, 20.0, False, False),
            (20.0, False, 20.0, False, False),
            (20.01, True, 20.01, False, False),
            (20.01, False, 20.0, True, True),
            (25.0, True, 25.0, False, False),
            (25.0, False, 20.0, True, True),
            (35.0, True, 35.0, False, False),
            (35.0, False, 20.0, True, True),
            (100.0, True, 100.0, False, False),
            (100.0, False, 20.0, True, True),
        ],
    )
    def test_domain_rules_interest_rates(
        self, rate, is_commercial, expected_applied_rate, expected_capped, expected_usury
    ):
        res = calculate_legal_formula(
            calculation_type="late_payment_interest",
            parameters={
                "principal_vnd": 100_000_000,
                "days_overdue": 365,
                "annual_interest_rate_percent": rate,
                "is_commercial_contract": is_commercial,
            },
        )
        assert res["ok"] is True
        assert res["applied_annual_rate_percent"] == pytest.approx(expected_applied_rate, abs=0.001)
        assert res["was_capped_at_statutory_limit"] is expected_capped
        assert res["is_usury_violation"] is expected_usury
        if is_commercial:
            assert "Điều 306 Luật Thương mại 2005" in res["legal_basis"]
            assert res["max_statutory_annual_rate_percent"] is None
        else:
            assert "Điều 468 Bộ luật Dân sự 2015" in res["legal_basis"]
            assert res["max_statutory_annual_rate_percent"] == 20.0

    def test_interest_days_and_principal_boundaries(self):
        """Test overdue interest across edge cases for days and principal."""
        # 0 days overdue
        res_0d = calculate_overdue_interest(100_000_000, 0, agreed_annual_rate=25.0, is_commercial_contract=True)
        assert res_0d.total_interest == 0.0
        assert res_0d.total_payable == 100_000_000.0

        # 0 principal
        res_0p = calculate_overdue_interest(0, 365, agreed_annual_rate=25.0, is_commercial_contract=True)
        assert res_0p.total_interest == 0.0
        assert res_0p.total_payable == 0.0

        # Negative days / principal clamped to 0
        res_neg = calculate_overdue_interest(-100, -10, agreed_annual_rate=25.0, is_commercial_contract=True)
        assert res_neg.principal_amount == 0.0
        assert res_neg.days_overdue == 0
        assert res_neg.total_interest == 0.0


# ==============================================================================
# SECTION 3: Severance Allowance Tenure & Rounding Stress Tests
# Art. 46 Labor Code 2019 & Art. 8 Decree 145/2020/ND-CP
# ==============================================================================


class TestSeveranceAllowanceTenureStress:
    """Stress tests for severance allowance service duration and Decree 145 rounding."""

    @pytest.mark.parametrize(
        "months,expected_qualifying_years,description",
        [
            # Under 12 months -> 0.0 qualifying years
            (0, 0.0, "0 months: no tenure"),
            (1, 0.0, "1 month: under 12 months"),
            (5, 0.0, "5 months: under 12 months"),
            (6, 0.0, "6 months: under 12 months"),
            (11, 0.0, "11 months: under 12 months"),
            (11.9, 0.0, "11.9 months: under 12 months"),
            # Exact 12 months -> 1.0 qualifying year
            (12, 1.0, "Exact 12 months (1 year, 0 odd months)"),
            (12.0, 1.0, "12.0 float months"),
            # 12 to 18 months: odd months 1 to 6 -> rounds to 0.5 year -> 1.5 years
            (13, 1.5, "13 months (1 yr + 1 mo <= 6) -> 1.5 yrs"),
            (14, 1.5, "14 months (1 yr + 2 mo <= 6) -> 1.5 yrs"),
            (15, 1.5, "15 months (1 yr + 3 mo <= 6) -> 1.5 yrs"),
            (16, 1.5, "16 months (1 yr + 4 mo <= 6) -> 1.5 yrs"),
            (17, 1.5, "17 months (1 yr + 5 mo <= 6) -> 1.5 yrs"),
            (18, 1.5, "18 months (1 yr + 6 mo <= 6) -> 1.5 yrs"),
            # 19 to 23 months: odd months 7 to 11 -> rounds to 1.0 year -> 2.0 years
            (19, 2.0, "19 months (1 yr + 7 mo > 6) -> 2.0 yrs"),
            (20, 2.0, "20 months (1 yr + 8 mo > 6) -> 2.0 yrs"),
            (21, 2.0, "21 months (1 yr + 9 mo > 6) -> 2.0 yrs"),
            (22, 2.0, "22 months (1 yr + 10 mo > 6) -> 2.0 yrs"),
            (23, 2.0, "23 months (1 yr + 11 mo > 6) -> 2.0 yrs"),
            # 24 months: exactly 2 years
            (24, 2.0, "24 months (2 yrs, 0 odd months) -> 2.0 yrs"),
            # 25 months: 2 yrs + 1 mo <= 6 -> 2.5 years
            (25, 2.5, "25 months (2 yrs + 1 mo <= 6) -> 2.5 yrs"),
            # 30 months: 2 yrs + 6 mo <= 6 -> 2.5 years
            (30, 2.5, "30 months (2 yrs + 6 mo <= 6) -> 2.5 yrs"),
            # 31 months: 2 yrs + 7 mo > 6 -> 3.0 years
            (31, 3.0, "31 months (2 yrs + 7 mo > 6) -> 3.0 yrs"),
            # 120 months (10 years)
            (120, 10.0, "120 months -> 10.0 yrs"),
            (126, 10.5, "126 months (10 yrs + 6 mo) -> 10.5 yrs"),
            (127, 11.0, "127 months (10 yrs + 7 mo) -> 11.0 yrs"),
        ],
    )
    def test_qualifying_working_years_function(self, months, expected_qualifying_years, description):
        actual = calculate_qualifying_working_years(months)
        assert actual == expected_qualifying_years, f"Failed for {description}: got {actual}"

    @pytest.mark.parametrize(
        "months,expected_allowance_factor,description",
        [
            (0, 0.0, "0 months -> 0 allowance"),
            (5, 0.0, "5 months -> 0 allowance"),
            (6, 0.0, "6 months -> 0 allowance"),
            (11, 0.0, "11 months -> 0 allowance"),
            (12, 0.5, "12 months -> 1.0 yr * 0.5 = 0.5 salary"),
            (14, 0.75, "14 months -> 1.5 yrs * 0.5 = 0.75 salary"),
            (18, 0.75, "18 months -> 1.5 yrs * 0.5 = 0.75 salary"),
            (19, 1.0, "19 months -> 2.0 yrs * 0.5 = 1.0 salary"),
            (24, 1.0, "24 months -> 2.0 yrs * 0.5 = 1.0 salary"),
            (25, 1.25, "25 months -> 2.5 yrs * 0.5 = 1.25 salary"),
        ],
    )
    def test_severance_allowance_endpoint(self, months, expected_allowance_factor, description):
        salary = 20_000_000.0
        expected_amount = expected_allowance_factor * salary

        # 1. Tool calculate_severance_allowance
        res = calculate_severance_allowance(monthly_salary=salary, months_worked=months)
        assert res.severance_allowance == pytest.approx(expected_amount, abs=1.0), f"Tool failed for {description}"

        # 2. Domain calculate_legal_formula
        res_domain = calculate_legal_formula(
            calculation_type="severance_allowance",
            parameters={"monthly_salary_vnd": salary, "months_worked": months},
        )
        assert res_domain["ok"] is True
        assert res_domain["total_severance_vnd"] == pytest.approx(expected_amount, abs=1.0), f"Domain failed for {description}"

    def test_illegal_termination_unemployment_insurance_interaction(self):
        """Under Art. 46 Labor Code 2019, time covered by unemployment insurance (BHTN) is excluded.

        When has_unemployment_insurance=True: severance_allowance = 0
        When has_unemployment_insurance=False: severance_allowance applies.
        """
        salary = 10_000_000.0
        months = 14

        # With BHTN
        res_with_bhtn = calculate_illegal_termination_compensation(
            monthly_salary=salary,
            months_worked=months,
            has_unemployment_insurance=True,
        )
        assert res_with_bhtn.severance_allowance == 0.0

        # Without BHTN
        res_without_bhtn = calculate_illegal_termination_compensation(
            monthly_salary=salary,
            months_worked=months,
            has_unemployment_insurance=False,
        )
        # 14 months -> 1.5 years -> 1.5 * 0.5 * 10M = 7.5M
        assert res_without_bhtn.severance_allowance == 7_500_000.0
        assert res_without_bhtn.total_compensation == res_with_bhtn.total_compensation + 7_500_000.0


# ==============================================================================
# SECTION 4: API Route Integration & Robustness Stress Tests
# POST /api/v1/documents/calculate/*
# ==============================================================================


class TestApiCalculatorsIntegrationStress:
    """Stress tests on HTTP endpoints in backend/api/routes/documents.py."""

    @pytest.fixture
    def client(self):
        from backend.api.routes.documents import router
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")
        return TestClient(app)

    def test_api_commercial_court_fee_10_billion(self, client):
        resp = client.post(
            "/api/v1/documents/calculate/court-fee",
            json={
                "claim_amount": 10_000_000_000,
                "dispute_type": "kinh doanh thương mại",
                "has_monetary_value": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["first_instance_fee"] == 150_000_000.0
        assert data["appellate_fee"] == 2_000_000.0

    def test_api_commercial_interest_uncapped(self, client):
        resp = client.post(
            "/api/v1/documents/calculate/interest",
            json={
                "principal_amount": 100_000_000,
                "days_overdue": 365,
                "agreed_annual_rate": 25.0,
                "is_commercial_contract": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["applied_annual_rate"] == 25.0
        assert data["is_capped_by_law"] is False
        assert data["warning_note"] is None

    def test_api_severance_tenure_rounding(self, client):
        # 14 months worked with has_unemployment_insurance=False
        resp = client.post(
            "/api/v1/documents/calculate/severance",
            json={
                "monthly_salary": 10_000_000,
                "months_worked": 14,
                "unemployed_months": 2,
                "days_without_notice": 0,
                "has_unemployment_insurance": False,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["severance_allowance"] == 7_500_000.0

    def test_domain_string_parameters_resilience(self):
        """Domain calculator should cleanly parse string parameter values."""
        # String numbers and string booleans
        res_interest = calculate_legal_formula(
            calculation_type="late_payment_interest",
            parameters={
                "principal_vnd": "100000000",
                "days_overdue": "365",
                "annual_interest_rate_percent": "25.0",
                "is_commercial_contract": "true",
            },
        )
        assert res_interest["ok"] is True
        assert res_interest["applied_annual_rate_percent"] == 25.0
        assert res_interest["was_capped_at_statutory_limit"] is False

        # Severance with string months
        res_sev = calculate_legal_formula(
            calculation_type="severance_allowance",
            parameters={
                "monthly_salary_vnd": "10000000",
                "months_worked": "14",
            },
        )
        assert res_sev["ok"] is True
        assert res_sev["qualifying_working_years"] == 1.5
        assert res_sev["total_severance_vnd"] == 7_500_000

