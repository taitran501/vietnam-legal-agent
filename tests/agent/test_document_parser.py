import pytest
from epr_agent.tools.document_parser import (
    parse_contract_clauses,
    parse_document_file,
)


def test_parse_contract_clauses():
    sample_text = """
HỢP ĐỒNG MUA BÁN HÀNG HÓA

Điều 1. Đối tượng hợp đồng
1. Bên A đồng ý bán và Bên B đồng ý mua lô hàng theo phụ lục.
2. Chất lượng hàng hóa theo tiêu chuẩn Việt Nam.

Điều 2. Giá cả và phương thức thanh toán
1. Tổng giá trị hợp đồng là 500.000.000 VNĐ.
2. Thanh toán thành 2 đợt bằng chuyển khoản.

Điều 3. Phạt vi phạm và bồi thường thiệt hại
1. Bên nào vi phạm hợp đồng phải chịu phạt vi phạm 15% giá trị hợp đồng.
"""
    clauses = parse_contract_clauses(sample_text)
    assert len(clauses) == 3
    assert clauses[0].clause_number == "1"
    assert "Đối tượng hợp đồng" in clauses[0].clause_title
    assert len(clauses[0].sub_clauses) == 2
    assert clauses[2].clause_number == "3"
    assert "15%" in clauses[2].full_text


def test_parse_document_file_txt():
    sample_bytes = "Điều 1. Điều khoản mở đầu\nNội dung điều 1.\n\nĐiều 2. Điều khoản kết\nNội dung điều 2.".encode("utf-8")
    result = parse_document_file(sample_bytes, filename="hop_dong.txt", mime_type="text/plain")
    assert result.file_type == "txt"
    assert len(result.clauses) == 2
    assert result.clauses[0].clause_number == "1"
