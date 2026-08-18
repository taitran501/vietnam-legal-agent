import pytest
from epr_agent.tools.document_parser import parse_contract_clauses
from epr_agent.tools.contract_redliner import review_contract_clauses_heuristic


def test_contract_redliner_heuristic_violations():
    contract_text = """
Điều 1. Công việc và thử việc
Người lao động đồng ý thử việc trong thời gian 90 ngày với mức lương thỏa thuận.

Điều 2. Phạt vi phạm hợp đồng
Nếu một bên vi phạm hợp đồng thì phải chịu phạt vi phạm 20% giá trị hợp đồng.

Điều 3. Lãi suất chậm trả
Trường hợp chậm thanh toán, bên mua phải chịu lãi suất 30% mỗi năm.

Điều 4. Bồi thường thiệt hại
Bên bán được miễn trừ toàn bộ trách nhiệm bồi thường thiệt hại trong mọi trường hợp.
"""
    clauses = parse_contract_clauses(contract_text)
    report = review_contract_clauses_heuristic(clauses, document_title="Hợp đồng dịch vụ")

    assert report.total_clauses == 4
    assert report.overall_risk == "high"
    assert report.high_risk_count >= 3

    # Check that high risk items have statutory conflicts
    conflicts = [c.statutory_conflict for c in report.clause_reviews if c.statutory_conflict]
    assert any("301" in c for c in conflicts)  # Luật Thương mại 8%
    assert any("468" in c for c in conflicts)  # BLDS 20%
    assert any("25" in c for c in conflicts)   # BLLĐ thử việc
