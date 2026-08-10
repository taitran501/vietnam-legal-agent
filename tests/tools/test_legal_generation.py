from epr_agent.domain.models import DocumentRecord
from epr_agent.tools.evidence import legal_claim_segments
from epr_agent.tools.generation import EvidenceGenerationGateway


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
