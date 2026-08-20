from epr_agent.tools.document_drafter import (
    CourtPetitionPayload,
    draft_court_petition_form_23,
    draft_safe_deposit_agreement,
    generate_docx_bytes,
)


def test_draft_court_petition_form_23():
    payload = CourtPetitionPayload(
        court_name="Tòa án nhân dân Quận Hoàn Kiếm, TP. Hà Nội",
        plaintiff_name="Nguyễn Văn A",
        plaintiff_dob="1985",
        plaintiff_id_card="001085001234",
        plaintiff_address="Số 12 phố Tràng Tiền, Hoàn Kiếm, Hà Nội",
        plaintiff_phone="0912345678",
        defendant_name="Công ty TNHH Bất động sản X",
        defendant_address="Số 45 phố Lý Thường Kiệt, Hoàn Kiếm, Hà Nội",
        defendant_phone="0243888999",
        case_summary="Bên bị kiện không trả lại 200 triệu đồng tiền đặt cọc mua căn hộ chung cư.",
        legal_basis_and_violations="Vi phạm quy định về đặt cọc theo Điều 328 Bộ luật Dân sự 2015.",
        petition_requests=[
            "Buộc bị đơn trả lại 200.000.000 VNĐ tiền cọc.",
            "Buộc bị đơn chịu phạt cọc 200.000.000 VNĐ.",
        ],
        evidence_list=[
            "Bản sao CCCD của người khởi kiện.",
            "Hợp đồng đặt cọc ngày 15/01/2026.",
            "Biên lai chuyển khoản ngân hàng số 999888.",
        ],
    )

    draft = draft_court_petition_form_23(payload)
    assert draft.document_type == "court_petition"
    assert "ĐƠN KHỞI KIỆN" in draft.plain_text
    assert "Tòa án nhân dân Quận Hoàn Kiếm" in draft.plain_text
    assert "Nguyễn Văn A" in draft.plain_text
    assert "200.000.000 VNĐ" in draft.plain_text
    assert len(draft.instructions) > 0


def test_draft_safe_deposit_agreement():
    draft = draft_safe_deposit_agreement(
        buyer_name="Trần Thị Lan",
        seller_name="Lê Văn Hùng",
        property_address="Số 88 đường Nguyễn Huệ, Quận 1, TP. HCM",
        deposit_amount=100000000,
        total_price=5000000000,
    )
    assert draft.document_type == "deposit_contract"
    assert "HỢP ĐỒNG ĐẶT CỌC" in draft.plain_text
    assert "100,000,000" in draft.plain_text
    assert "5,000,000,000" in draft.plain_text
    assert "Điều 328" in draft.legal_basis


def test_generate_docx_bytes():
    docx = generate_docx_bytes(title="Đơn khởi kiện", content="CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\nĐộc lập - Tự do - Hạnh phúc\n\nNội dung đơn.")
    assert isinstance(docx, bytes)
    assert len(docx) > 500
    # Valid zip package signature
    assert docx[:2] == b"PK"
