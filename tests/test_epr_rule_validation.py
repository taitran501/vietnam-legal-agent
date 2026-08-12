from epr_agent.domain.epr_rules import evaluate_assessment
from epr_agent.domain.v4 import AssessmentStatus, FactSource, FactValue


def _facts(**values: str) -> dict[str, FactValue]:
    return {
        key: FactValue(value=value, source=FactSource.CASE_PANEL, confirmation_status="user_confirmed")
        for key, value in values.items()
    }


def test_fractional_revenue_cannot_be_coerced_into_an_exemption():
    result = evaluate_assessment(
        _facts(
            business_role="manufacturer",
            object_kind="commercial_packaging",
            product_group="bao_bi",
            packaged_goods_category="thuc_pham",
            market_placement="vietnam_market",
            activity_purpose="commercial",
            annual_revenue_vnd="29999999999.5",
            reused_by_producer="no",
        ),
        evidence_ids={},
    )
    assert result.status == AssessmentStatus.CANNOT_DETERMINE


def test_generic_other_category_is_not_a_false_exemption():
    result = evaluate_assessment(
        _facts(
            business_role="manufacturer",
            object_kind="commercial_packaging",
            product_group="bao_bi",
            packaged_goods_category="other",
            market_placement="vietnam_market",
            activity_purpose="commercial",
            annual_revenue_vnd="1000000000",
            reused_by_producer="no",
        ),
        evidence_ids={},
    )
    assert result.status == AssessmentStatus.CANNOT_DETERMINE


def test_recovery_rate_is_bounded():
    result = evaluate_assessment(
        _facts(
            business_role="manufacturer",
            object_kind="commercial_packaging",
            product_group="bao_bi",
            packaged_goods_category="thuc_pham",
            market_placement="vietnam_market",
            activity_purpose="commercial",
            annual_revenue_vnd="40000000000",
            reused_by_producer="yes",
            recovery_rate="101",
        ),
        evidence_ids={},
    )
    assert result.status == AssessmentStatus.CANNOT_DETERMINE
