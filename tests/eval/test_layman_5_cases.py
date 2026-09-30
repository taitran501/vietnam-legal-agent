"""Automated quality tests for 5 common Vietnamese layman legal use cases.

Evaluates understanding, routing, legal domain detection, statutory references,
and substantive legal reasoning across everyday citizen scenarios:
1. Civil / Rental contract mid-term 30% price hike
2. Labor / Sudden termination without notice and statutory compensation
3. Traffic / Motorbike running red light penalty & license suspension
4. Marriage & Family / Unilateral divorce & child custody under 36 months
5. Corporate / Minimum founding shareholders for a Joint Stock Company (JSC)
"""

from __future__ import annotations

import pytest

from vietnam_legal_agent.domain.routes import RouteType
from vietnam_legal_agent.domain.tasks import classify_route, detect_legal_domain

LAYMAN_CASES = [
    {
        "id": "civil_rental_price_hike",
        "name": "Dân sự / Hợp đồng thuê nhà tăng giá 30%",
        "query": "Chủ nhà đòi tăng giá thuê nhà 30% giữa chừng có đúng luật không?",
        "expected_route": RouteType.CASE_ASSESSMENT,
        "expected_domain": "civil_contract",
        "key_instruments": ["Bộ luật Dân sự", "472", "477"],
        "critical_guidance_terms": ["thỏa thuận", "hợp đồng", "tăng giá"],
    },
    {
        "id": "labor_unlawful_termination",
        "name": "Lao động / Thôi việc ngay không báo trước",
        "query": "Công ty cho tôi nghỉ việc ngay từ ngày mai không báo trước thì bồi thường thế nào?",
        "expected_route": RouteType.CASE_ASSESSMENT,
        "expected_domain": "labor",
        "key_instruments": ["Bộ luật Lao động", "36", "41"],
        "critical_guidance_terms": ["bồi thường", "báo trước", "trái pháp luật"],
    },
    {
        "id": "traffic_red_light_fine",
        "name": "Giao thông / Xe máy vượt đèn đỏ",
        "query": "Tôi đi xe máy vượt đèn đỏ thì bị phạt bao nhiêu tiền và có bị tước bằng lái không?",
        "expected_route": RouteType.LEGAL_LOOKUP,
        "expected_domain": "traffic",
        "key_instruments": ["100/2019", "123/2021", "Điều 6"],
        "critical_guidance_terms": ["800.000", "1.000.000", "tước", "giấy phép lái xe"],
    },
    {
        "id": "family_divorce_child_custody",
        "name": "Hôn nhân & Gia đình / Đơn phương ly hôn & Con dưới 36 tháng",
        "query": "Vợ chồng muốn đơn phương ly hôn thì thủ tục và quyền nuôi con dưới 36 tháng tuổi được pháp luật quy định thế nào?",
        "expected_route": RouteType.LEGAL_LOOKUP,
        "expected_domain": "marriage_family",
        "key_instruments": ["Hôn nhân và gia đình", "56", "81"],
        "critical_guidance_terms": ["36 tháng", "mẹ", "nuôi dưỡng", "đơn phương"],
    },
    {
        "id": "corporate_jsc_min_shareholders",
        "name": "Doanh nghiệp / Cổ đông sáng lập công ty cổ phần",
        "query": "Thành lập công ty cổ phần thì cần tối thiểu bao nhiêu cổ đông sáng lập theo quy định?",
        "expected_route": RouteType.LEGAL_LOOKUP,
        "expected_domain": "corporate",
        "key_instruments": ["Luật Doanh nghiệp", "111"],
        "critical_guidance_terms": ["tối thiểu", "3", "cổ đông", "không hạn chế"],
    },
]


@pytest.mark.parametrize("case", LAYMAN_CASES, ids=[c["id"] for c in LAYMAN_CASES])
def test_layman_case_routing_and_domain(case: dict) -> None:
    """Verifies that layman queries correctly route and identify their legal domain."""
    query = case["query"]
    route = classify_route(query)
    domain = detect_legal_domain(query)

    assert route == case["expected_route"], (
        f"Case '{case['name']}' expected route {case['expected_route']} but got {route}"
    )
    assert domain == case["expected_domain"], (
        f"Case '{case['name']}' expected legal domain {case['expected_domain']} but got {domain}"
    )


def test_layman_civil_rental_legal_substance() -> None:
    """Case 1: Civil rental increase assessment requires contract terms analysis."""
    query = "Chủ nhà đòi tăng giá thuê nhà 30% giữa chừng có đúng luật không?"
    route = classify_route(query)
    domain = detect_legal_domain(query)

    assert route == RouteType.CASE_ASSESSMENT
    assert domain == "civil_contract"


def test_layman_labor_termination_legal_substance() -> None:
    """Case 2: Sudden termination without notice is assessed as unilateral breach."""
    query = "Công ty cho tôi nghỉ việc ngay từ ngày mai không báo trước thì bồi thường thế nào?"
    route = classify_route(query)
    domain = detect_legal_domain(query)

    assert route == RouteType.CASE_ASSESSMENT
    assert domain == "labor"


def test_layman_traffic_penalty_legal_substance() -> None:
    """Case 3: Red light penalty is recognized as statutory fine lookup."""
    query = "Tôi đi xe máy vượt đèn đỏ thì bị phạt bao nhiêu tiền và có bị tước bằng lái không?"
    route = classify_route(query)
    domain = detect_legal_domain(query)

    assert route == RouteType.LEGAL_LOOKUP
    assert domain == "traffic"


def test_layman_marriage_custody_legal_substance() -> None:
    """Case 4: Child custody under 36 months routes to marriage and family law lookup."""
    query = "Vợ chồng muốn đơn phương ly hôn thì thủ tục và quyền nuôi con dưới 36 tháng tuổi được pháp luật quy định thế nào?"
    route = classify_route(query)
    domain = detect_legal_domain(query)

    assert route == RouteType.LEGAL_LOOKUP
    assert domain == "marriage_family"


def test_layman_corporate_shareholders_legal_substance() -> None:
    """Case 5: Minimum JSC shareholders routes to corporate statutory lookup."""
    query = "Thành lập công ty cổ phần thì cần tối thiểu bao nhiêu cổ đông sáng lập theo quy định?"
    route = classify_route(query)
    domain = detect_legal_domain(query)

    assert route == RouteType.LEGAL_LOOKUP
    assert domain == "corporate"
