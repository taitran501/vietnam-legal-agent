from epr_agent.domain.models import DocumentRecord
from epr_agent.tools.evidence import legal_claim_segments
from epr_agent.tools.generation import EvidenceGenerationGateway, _answer_preserves_source_exceptions


def test_legal_lookup_renderer_keeps_each_claim_attached_to_exact_chunk():
    documents = [
        DocumentRecord(
            content="Nhà sản xuất, nhập khẩu phải thực hiện trách nhiệm tái chế sản phẩm, bao bì.",
            document_id="law-77-1",
            source="legal",
            metadata={
                "Dieu": "Điều 77. Đối tượng thực hiện trách nhiệm tái chế",
                "source_title": "Nghị định 08/2022/NĐ-CP",
            },
        )
    ]

    answer = EvidenceGenerationGateway._compose_legal_route_answer(documents)

    assert "[1]" in answer
    assert "Nguồn tham khảo" in answer
    assert legal_claim_segments(answer) == [
        (
            "Theo Điều 77. Đối tượng thực hiện trách nhiệm tái chế, văn bản quy định: "
            "Nhà sản xuất, nhập khẩu phải thực hiện trách nhiệm tái chế sản phẩm, bao bì. [1]"
        )
    ]


def test_legal_synthesis_falls_back_when_it_omits_a_cross_referenced_exception():
    source = DocumentRecord(
        content=(
            "Điều 54. Trách nhiệm tái chế\n\n"
            "1. Tổ chức sản xuất phải thực hiện tái chế theo tỷ lệ bắt buộc.\n\n"
            "2. Tổ chức được chọn một trong các hình thức sau đây:\n"
            "a) Tổ chức tái chế sản phẩm, bao bì;\n"
            "b) Đóng góp tài chính vào Quỹ Bảo vệ môi trường Việt Nam.\n\n"
            "3. Tổ chức phải đăng ký kế hoạch tái chế và báo cáo kết quả hằng năm, "
            "trừ trường hợp quy định tại điểm b khoản 2 Điều này."
        ),
        document_id="law-epr-54",
        source="legal",
        metadata={"Dieu": "Điều 54", "source_title": "Luật Bảo vệ môi trường"},
    )
    incomplete = (
        "Tổ chức phải đăng ký kế hoạch tái chế và báo cáo kết quả hằng năm [1]. "
        "Có thể chọn đóng góp tài chính vào Quỹ Bảo vệ môi trường [1]."
    )
    qualified = (
        "Tổ chức phải đăng ký kế hoạch tái chế và báo cáo kết quả hằng năm, "
        "trừ trường hợp chọn đóng góp tài chính theo điểm b khoản 2 [1]."
    )

    assert _answer_preserves_source_exceptions(incomplete, [source]) is False
    assert _answer_preserves_source_exceptions(qualified, [source]) is True

    extractive = EvidenceGenerationGateway._compose_legal_route_answer([source])
    assert "trừ trường hợp quy định tại điểm b khoản 2 Điều này" in extractive
