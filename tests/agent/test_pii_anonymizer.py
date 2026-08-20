"""Unit tests for PII Anonymizer."""

from epr_agent.infra.pii_anonymizer import (
    anonymize_payload,
    anonymize_text,
    has_pii,
)


def test_mask_cccd_and_cmnd():
    text_12 = "Số CCCD của tôi là 079099123456 tại TP.HCM"
    masked = anonymize_text(text_12)
    assert "079******456" in masked
    assert "079099123456" not in masked

    text_9 = "CMND cũ số 025123456 cấp năm 2010"
    masked_9 = anonymize_text(text_9)
    assert "02*****56" in masked_9
    assert "025123456" not in masked_9


def test_mask_phone_numbers():
    text = "Liên hệ với luật sư qua số 0903123456 hoặc 0389876543"
    masked = anonymize_text(text)
    assert "090****456" in masked
    assert "038****543" in masked
    assert "0903123456" not in masked


def test_mask_email():
    text = "Gửi tài liệu về email nguyenvana@gmail.com hoặc contact@lawfirm.vn"
    masked = anonymize_text(text)
    assert "n***@gmail.com" in masked
    assert "c***@lawfirm.vn" in masked
    assert "nguyenvana@gmail.com" not in masked


def test_has_pii_detection():
    assert has_pii("Tôi là Trần Văn A, CCCD 079099123456") is True
    assert has_pii("Số điện thoại 0912345678") is True
    assert has_pii("Email: test@example.com") is True
    assert has_pii("Nghị định 08/2022/NĐ-CP quy định chi tiết thi hành Luật BVMT") is False


def test_anonymize_payload_dict():
    raw_payload = {
        "user_name": "Nguyễn Văn B",
        "facts": {
            "id_card": "079099999888",
            "phone": "0987654321",
            "note": "Thuê nhà tại số 123 đường ABC",
        },
        "tags": ["client", "0911223344"],
    }
    cleaned = anonymize_payload(raw_payload)
    assert cleaned["facts"]["id_card"] == "079******888"
    assert cleaned["facts"]["phone"] == "098****321"
    assert cleaned["tags"][1] == "091****344"
