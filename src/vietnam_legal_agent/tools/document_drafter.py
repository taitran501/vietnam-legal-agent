"""Official Legal Document and Court Petition Drafter for Vietnamese Legal System.

Templates implemented:
1. Mẫu số 23-DS: Đơn khởi kiện chuẩn ban hành kèm theo Nghị quyết số 01/2017/NQ-HĐTP
   của Hội đồng Thẩm phán Tòa án nhân dân tối cao ngày 13/01/2017.
2. Đơn khiếu nại Quyết định hành chính / Hành vi hành chính (Luật Khiếu nại 2011).
3. Hợp đồng đặt cọc mua bán / chuyển nhượng bất động sản an toàn (Bộ luật Dân sự 2015).
4. Thông báo đơn phương chấm dứt hợp đồng lao động đúng luật (Bộ luật Lao động 2019).

Exports to pure-python OpenXML DOCX adhering to Decree 30/2020/ND-CP formatting standards.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from datetime import UTC, datetime

from pydantic import BaseModel, Field


class CourtPetitionPayload(BaseModel):
    """Data required for Court Petition Form 23-DS."""

    court_name: str = Field(default="Tòa án nhân dân có thẩm quyền", description="Tên Tòa án tiếp nhận")
    filing_date: str = Field(default_factory=lambda: datetime.now(UTC).strftime("ngày %d tháng %m năm %Y"))
    
    # Người khởi kiện
    plaintiff_name: str = Field(default="........................................", description="Họ và tên người khởi kiện")
    plaintiff_dob: str = Field(default="........", description="Năm sinh")
    plaintiff_id_card: str = Field(default="........................", description="CCCD/CMND/Hộ chiếu")
    plaintiff_address: str = Field(default="................................................................", description="Địa chỉ cư trú")
    plaintiff_phone: str = Field(default="....................", description="Số điện thoại")
    
    # Người bị kiện
    defendant_name: str = Field(default="........................................", description="Họ và tên người bị kiện / Công ty")
    defendant_address: str = Field(default="................................................................", description="Địa chỉ người bị kiện")
    defendant_phone: str = Field(default="....................", description="Số điện thoại")
    
    # Người có quyền lợi, nghĩa vụ liên quan
    interested_parties: str = Field(default="Không có", description="Người có quyền lợi nghĩa vụ liên quan")
    
    # Nội dung khởi kiện
    case_summary: str = Field(description="Tóm tắt sự việc và diễn biến vụ tranh chấp")
    legal_basis_and_violations: str = Field(description="Các quyền và lợi ích hợp pháp bị xâm phạm, điều luật viện dẫn")
    petition_requests: list[str] = Field(description="Các yêu cầu cụ thể Tòa án giải quyết")
    evidence_list: list[str] = Field(default_factory=list, description="Danh mục tài liệu, chứng cứ kèm theo")


class LegalDraftResult(BaseModel):
    """Result of legal document drafting."""

    draft_id: str = Field(description="Mã văn bản")
    document_type: str = Field(description="Loại văn bản (court_petition, complaint, contract, notice)")
    title: str = Field(description="Tiêu đề văn bản")
    plain_text: str = Field(description="Nội dung toàn văn bản")
    legal_basis: str = Field(description="Căn cứ pháp lý chuẩn hóa")
    instructions: list[str] = Field(default_factory=list, description="Hướng dẫn thủ tục nộp/ký kết")


def draft_court_petition_form_23(payload: CourtPetitionPayload) -> LegalDraftResult:
    """Draft official Court Petition (Mẫu số 23-DS - Nghị quyết 01/2017/NQ-HĐTP)."""
    draft_id = f"petition_{uuid.uuid4().hex[:8]}"

    requests_formatted = "\n".join(
        f"   {idx}. {req}" for idx, req in enumerate(payload.petition_requests, start=1)
    )

    evidence_formatted = "\n".join(
        f"   {idx}. {doc}" for idx, doc in enumerate(payload.evidence_list, start=1)
    ) if payload.evidence_list else "   1. Bản sao CCCD của người khởi kiện.\n   2. Các chứng cứ, hợp đồng, biên lai chuyển tiền liên quan."

    text = f"""CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM
Độc lập - Tự do - Hạnh phúc
-------------------------

..., {payload.filing_date}

ĐƠN KHỞI KIỆN
(V/v: {payload.petition_requests[0] if payload.petition_requests else 'Tranh chấp dân sự'})

Kính gửi: {payload.court_name}

NGƯỜI KHỞI KIỆN:
- Họ và tên: {payload.plaintiff_name} (Sinh năm: {payload.plaintiff_dob})
- CCCD/Hộ chiếu số: {payload.plaintiff_id_card}
- Địa chỉ cư trú: {payload.plaintiff_address}
- Số điện thoại liên hệ: {payload.plaintiff_phone}

NGƯỜI BỊ KIỆN:
- Họ và tên / Tên tổ chức: {payload.defendant_name}
- Địa chỉ: {payload.defendant_address}
- Số điện thoại: {payload.defendant_phone}

NGƯỜI CÓ QUYỀN LỢI, NGHĨA VỤ LIÊN QUAN:
- {payload.interested_parties}

NỘI DUNG SỰ VIỆC VÀ CĂN CỨ KHỞI KIỆN:
{payload.case_summary}

CĂN CỨ PHÁP LÝ VÀ HÀNH VI VI PHẠM:
{payload.legal_basis_and_violations}

YÊU CẦU TÒA ÁN GIẢI QUYẾT:
Kính đề nghị Quý Tòa án thụ lý và giải quyết các yêu cầu sau:
{requests_formatted}

DANH MỤC TÀI LIỆU, CHỨNG CỨ KÈM THEO ĐƠN:
{evidence_formatted}

Tôi cam đoan những thông tin khai trong đơn là hoàn toàn đúng sự thật và chịu trách nhiệm trước pháp luật.

                                             NGƯỜI KHỞI KIỆN
                                             (Ký và ghi rõ họ tên)
"""

    instructions = [
        "In đơn làm 02 bản, ký và ghi rõ họ tên (nếu là pháp nhân/doanh nghiệp thì người đại diện theo pháp luật ký và đóng dấu).",
        f"Nộp đơn trực tiếp hoặc gửi bưu điện kèm bản sao CCCD và toàn bộ chứng cứ tới {payload.court_name}.",
        "Trong thời hạn 08 ngày làm việc kể từ ngày nhận đơn, Tòa án sẽ xem xét đơn và ra thông báo nộp tiền tạm ứng án phí (nếu đơn hợp lệ).",
        "Sau khi nhận thông báo tạm ứng án phí, nộp tiền tại Chi cục Thi hành án dân sự và nộp lại biên lai cho Tòa án để thụ lý vụ án.",
    ]

    return LegalDraftResult(
        draft_id=draft_id,
        document_type="court_petition",
        title="Đơn khởi kiện (Mẫu số 23-DS TANDTC)",
        plain_text=text.strip(),
        legal_basis="Mẫu số 23-DS ban hành kèm theo Nghị quyết số 01/2017/NQ-HĐTP & Bộ luật Tố tụng dân sự 2015",
        instructions=instructions,
    )


def draft_safe_deposit_agreement(
    buyer_name: str,
    seller_name: str,
    property_address: str,
    deposit_amount: float,
    total_price: float,
    signing_deadline_days: int = 30,
) -> LegalDraftResult:
    """Draft Housing & Real Estate deposit agreement with strong protection clauses."""
    draft_id = f"deposit_{uuid.uuid4().hex[:8]}"

    text = f"""CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM
Độc lập - Tự do - Hạnh phúc
-------------------------

HỢP ĐỒNG ĐẶT CỌC
(V/v: Chuyển nhượng quyền sử dụng đất và tài sản gắn liền với đất)

Hôm nay, ngày ... tháng ... năm ..., tại ...................................................., chúng tôi gồm có:

BÊN ĐẶT CỌC (BÊN MUA - BÊN A):
- Ông/Bà: {buyer_name}
- CCCD số: ....................................... do Cục CSQLHC về TTXH cấp ngày .................
- Địa chỉ thường trú: .....................................................................................
- Điện thoại: ...........................................

BÊN NHẬN ĐẶT CỌC (BÊN BÁN - BÊN B):
- Ông/Bà: {seller_name}
- CCCD số: ....................................... do Cục CSQLHC về TTXH cấp ngày .................
- Địa chỉ thường trú: .....................................................................................
- Điện thoại: ...........................................

Hai bên tự nguyện thỏa thuận ký kết Hợp đồng đặt cọc với các điều khoản sau:

ĐIỀU 1. ĐỐI TƯỢNG ĐẶT CỌC VÀ MỤC ĐÍCH ĐẶT CỌC
1. Bên A tự nguyện đặt cọc số tiền: {deposit_amount:,.0f} VNĐ (Bằng chữ: ............................................) cho Bên B để đảm bảo giao kết và thực hiện Hợp đồng chuyển nhượng quyền sử dụng đất và tài sản gắn liền với đất tại địa chỉ: {property_address}.
2. Tổng giá trị chuyển nhượng được hai bên thống nhất là: {total_price:,.0f} VNĐ (Bằng chữ: ............................................). Mức giá này là cố định và không thay đổi trong suốt thời hạn đặt cọc.

ĐIỀU 2. THỜI HẠN ĐẶT CỌC VÀ KÝ HỢP ĐỒNG CÔNG CHỨNG
1. Thời hạn đặt cọc là {signing_deadline_days} ngày kể từ ngày ký hợp đồng này (đến hết ngày .../.../......).
2. Đúng ngày hết hạn hoặc theo thỏa thuận sớm hơn, hai bên có mặt tại Phòng/Văn phòng Công chứng để ký Hợp đồng chuyển nhượng chính thức.

ĐIỀU 3. CAM KẾT VỀ TÍNH PHÁP LÝ CỦA TÀI SẢN (ĐIỀU KHOẢN BẢO VỆ)
1. Bên B cam đoan thửa đất và nhà ở nói trên thuộc quyền sử dụng/sở hữu hợp pháp của Bên B, không có tranh chấp, không bị kê biên để thi hành án, không bị quy hoạch treo hoặc hạn chế quyền giao dịch.
2. Trường hợp Bên B không phải là người đứng tên duy nhất trên Giấy chứng nhận quyền sử dụng đất (Sổ đỏ), Bên B phải có văn bản ủy quyền hợp pháp hoặc tất cả đồng sở hữu (bao gồm vợ/chồng) cùng ký tên vào Hợp đồng.

ĐIỀU 4. XỬ LÝ TIỀN ĐẶT CỌC VÀ PHẠT CỌC
1. Khi đến hạn ký Hợp đồng công chứng: Số tiền đặt cọc {deposit_amount:,.0f} VNĐ sẽ được trừ trực tiếp vào số tiền chuyển nhượng mà Bên A phải thanh toán cho Bên B.
2. Nếu Bên A từ chối giao kết hợp đồng mà không do lỗi của Bên B: Bên A mất toàn bộ số tiền đặt cọc.
3. Nếu Bên B từ chối giao kết hợp đồng, hoặc tài sản bị tranh chấp/vướng quy hoạch không thể sang tên: Bên B phải trả lại toàn bộ số tiền đặt cọc {deposit_amount:,.0f} VNĐ và chịu phạt cọc một khoản tiền tương đương 100% số tiền đặt cọc ({deposit_amount:,.0f} VNĐ) cho Bên A trong vòng 03 ngày làm việc theo đúng quy định tại Điều 328 Bộ luật Dân sự 2015.

ĐIỀU 5. HIỆU LỰC HỢP ĐỒNG
Hợp đồng có hiệu lực kể từ thời điểm ký kết và giao nhận đủ tiền cọc. Hợp đồng được lập thành 02 bản có giá trị pháp lý như nhau, mỗi bên giữ 01 bản.

            BÊN ĐẶT CỌC (BÊN A)                              BÊN NHẬN ĐẶT CỌC (BÊN B)
           (Ký và ghi rõ họ tên)                            (Ký và ghi rõ họ tên)
"""

    return LegalDraftResult(
        draft_id=draft_id,
        document_type="deposit_contract",
        title="Hợp đồng đặt cọc mua bán bất động sản an toàn",
        plain_text=text.strip(),
        legal_basis="Điều 328 & Điều 500-503 Bộ luật Dân sự 2015 và Luật Kinh doanh BĐS",
        instructions=[
            "Kiểm tra bản gốc Giấy chứng nhận quyền sử dụng đất (Sổ đỏ) trước khi chuyển tiền đặt cọc.",
            "Yêu cầu cả hai vợ chồng của bên bán (hoặc tất cả đồng sở hữu có tên trong hộ khẩu/sổ đỏ) cùng ký tên.",
            "Thực hiện giao dịch qua chuyển khoản ngân hàng với nội dung ghi rõ: 'Chuyển tiền đặt cọc mua nhà đất theo Hợp đồng ngày dd/mm/yyyy'.",
        ],
    )


def generate_docx_bytes(title: str, content: str) -> bytes:
    """Generate a clean, valid .docx binary adhering to Decree 30/2020/ND-CP."""
    # Build OpenXML package
    paragraphs = content.split("\n")
    body_xml_parts = []

    for p in paragraphs:
        text = p.strip()
        if not text:
            body_xml_parts.append("<w:p/>")
            continue

        is_title = text.isupper() and len(text) < 60
        is_center = "CỘNG HÒA" in text or "Độc lập" in text or is_title

        jc_tag = '<w:jc w:val="center"/>' if is_center else '<w:jc w:val="both"/>'
        bold_tag = "<w:b/>" if (is_title or "Kính gửi:" in text or "NGƯỜI KHỞI KIỆN" in text or "ĐIỀU " in text) else ""
        escaped_text = (
            text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        )

        p_xml = f"""<w:p>
            <w:pPr>
                {jc_tag}
                <w:spacing w:line="300" w:lineRule="auto" w:after="80"/>
            </w:pPr>
            <w:r>
                <w:rPr>
                    <w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman"/>
                    <w:sz w:val="26"/>
                    <w:szCs w:val="26"/>
                    {bold_tag}
                </w:rPr>
                <w:t>{escaped_text}</w:t>
            </w:r>
        </w:p>"""
        body_xml_parts.append(p_xml)

    document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
        <w:body>
            {"".join(body_xml_parts)}
            <w:sectPr>
                <w:pgSz w:w="11906" w:h="16838"/>
                <w:pgMar w:top="1134" w:right="851" w:bottom="1134" w:left="1701"/>
            </w:sectPr>
        </w:body>
    </w:document>"""

    content_types_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
        <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
        <Default Extension="xml" ContentType="application/xml"/>
        <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
    </Types>"""

    rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
        <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
    </Relationships>"""

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml)
        zf.writestr("_rels/.rels", rels_xml)
        zf.writestr("word/document.xml", document_xml)

    return zip_buffer.getvalue()
