"""Deterministic EPR decision rules used by the V4 case routes.

The rule pack deliberately owns legal applicability.  An LLM may extract a
fact from a user message and explain an already-made decision; it never fills
unknown business facts or decides coverage from a similarity score.
"""

from __future__ import annotations

import re
from typing import Literal, cast

from epr_agent.domain.v4 import (
    CASE_FIELD_LABELS,
    AssessmentReason,
    AssessmentResult,
    AssessmentStatus,
    CaseField,
    FactSource,
    FactValue,
    LegalIssue,
)

EPR_RULE_PACK_VERSION = "epr-article-77-v1"

_PRODUCT_GROUPS = {
    "bao bì": "bao_bi",
    "ắc quy": "ac_quy",
    "pin": "pin",
    "dầu nhớt": "dau_nhot",
    "dầu nhờn": "dau_nhot",
    "săm lốp": "sam_lop",
    "lốp": "sam_lop",
    "điện tử": "dien_tu",
    "điện - điện tử": "dien_tu",
    "điện – điện tử": "dien_tu",
    "phương tiện": "phuong_tien",
    "ô tô": "phuong_tien",
    "xe máy": "phuong_tien",
}

_PACKAGED_CATEGORIES = {
    "thực phẩm": "thuc_pham",
    "mỹ phẩm": "my_pham",
    "thuốc": "thuoc",
    "phân bón": "phan_bon_thuc_an_thu_y",
    "thức ăn chăn nuôi": "phan_bon_thuc_an_thu_y",
    "thuốc thú y": "phan_bon_thuc_an_thu_y",
    "tẩy rửa": "che_pham_tay_rua",
    "xi măng": "xi_mang",
}


def _normalise(value: str) -> str:
    return " ".join((value or "").lower().split())


def _fact(value: str, source: FactSource, span: str, *, turn_id: str = "") -> FactValue:
    return FactValue(value=value, source=source, evidence_span=span, source_turn=turn_id, verified=False)


def extract_explicit_epr_facts(query: str, *, source: FactSource = FactSource.USER_TURN, turn_id: str = "") -> dict[str, FactValue]:
    """Extract only literal, visible user facts for the EPR rule pack."""

    text = _normalise(query)
    found: dict[str, FactValue] = {}
    if re.search(r"nhà\s*sản\s*xuất|sản\s*xuất", text):
        found["business_role"] = _fact("manufacturer", source, "nhà sản xuất", turn_id=turn_id)
    elif re.search(r"nhà\s*nhập\s*khẩu|nhập\s*khẩu", text):
        found["business_role"] = _fact("importer", source, "nhập khẩu", turn_id=turn_id)

    if "nguyên liệu" in text:
        found["object_kind"] = _fact("raw_material", source, "nguyên liệu", turn_id=turn_id)
    elif "chất thải" in text or "phát sinh trong quá trình sản xuất" in text:
        found["object_kind"] = _fact("production_waste", source, "chất thải", turn_id=turn_id)
    elif "bao bì" in text:
        found["object_kind"] = _fact("commercial_packaging", source, "bao bì", turn_id=turn_id)
        found["product_group"] = _fact("bao_bi", source, "bao bì", turn_id=turn_id)
    else:
        for marker, group in _PRODUCT_GROUPS.items():
            if marker in text:
                found["object_kind"] = _fact("product", source, marker, turn_id=turn_id)
                found["product_group"] = _fact(group, source, marker, turn_id=turn_id)
                break

    for marker, category in _PACKAGED_CATEGORIES.items():
        if marker in text:
            found["packaged_goods_category"] = _fact(category, source, marker, turn_id=turn_id)
            break
    if "hàng hóa khác" in text or "nhóm hàng hóa khác" in text:
        found["packaged_goods_category"] = _fact("other", source, "hàng hóa khác", turn_id=turn_id)
    for marker, material in (("pet", "pet"), ("pe", "pe_pp"), ("pp", "pe_pp"), ("nhựa", "plastic"), ("giấy", "paper"), ("thủy tinh", "glass"), ("kim loại", "metal"), ("cao su", "rubber")):
        if marker in text:
            found["material"] = _fact(material, source, marker, turn_id=turn_id)
            break

    if re.search(r"chỉ\s*xuất\s*khẩu|xuất\s*khẩu\s*toàn\s*bộ", text):
        found["market_placement"] = _fact("export_only", source, "xuất khẩu", turn_id=turn_id)
    elif "tạm nhập" in text and "tái xuất" in text:
        found["market_placement"] = _fact("temporary_import_reexport", source, "tạm nhập tái xuất", turn_id=turn_id)
    elif "đưa ra thị trường việt nam" in text or "bán tại việt nam" in text or "thị trường việt nam" in text:
        found["market_placement"] = _fact("vietnam_market", source, "thị trường Việt Nam", turn_id=turn_id)

    if any(marker in text for marker in ("nghiên cứu", "học tập", "thử nghiệm")):
        found["activity_purpose"] = _fact("research_study_test", source, "nghiên cứu/học tập/thử nghiệm", turn_id=turn_id)
    elif any(marker in text for marker in ("kinh doanh", "thương mại", "bán ra", "bán tại")):
        # Only accept an explicitly stated commercial purpose.  A business
        # role or the phrase "tại Việt Nam" is not enough to infer this fact.
        found["activity_purpose"] = _fact("commercial", source, "hoạt động thương mại", turn_id=turn_id)

    revenue = re.search(r"(?:doanh thu[^\d]{0,40})?(\d+(?:[.,]\d+)?)\s*(tỷ|triệu)?\s*(?:đồng|vnđ|vnd)?", text)
    if revenue and ("doanh thu" in text or "tỷ" in text):
        amount = float(revenue.group(1).replace(",", "."))
        unit = revenue.group(2) or ""
        if unit == "tỷ":
            amount *= 1_000_000_000
        elif unit == "triệu":
            amount *= 1_000_000
        found["annual_revenue_vnd"] = _fact(str(int(amount)), source, revenue.group(0), turn_id=turn_id)
    if "không thu hồi" in text or "không tái sử dụng" in text:
        found["reused_by_producer"] = _fact("no", source, "không thu hồi", turn_id=turn_id)
    elif "thu hồi" in text and ("tái sử dụng" in text or "đóng gói lại" in text):
        found["reused_by_producer"] = _fact("yes", source, "thu hồi/tái sử dụng", turn_id=turn_id)
    return found


def _value(facts: dict[str, FactValue], key: str) -> str:
    item = facts.get(key)
    return item.value if item else ""


def required_fact_keys(facts: dict[str, FactValue]) -> list[str]:
    """Return decision-changing facts in the order the agent should ask them."""

    required = ["business_role", "object_kind", "product_group", "market_placement"]
    product_group = _value(facts, "product_group")
    market = _value(facts, "market_placement")
    if market not in {"export_only", "temporary_import_reexport"}:
        required.append("activity_purpose")
    if product_group == "bao_bi":
        required.append("packaged_goods_category")
        if market == "vietnam_market":
            required.append("annual_revenue_vnd")
            required.append("reused_by_producer")
            if _value(facts, "reused_by_producer") == "yes":
                required.append("recovery_rate")
    return required


def missing_fact_keys(facts: dict[str, FactValue]) -> list[str]:
    return [key for key in required_fact_keys(facts) if not _value(facts, key)]


def case_fields(facts: dict[str, FactValue], missing: list[str]) -> list[CaseField]:
    required = set(required_fact_keys(facts))
    options = {
        "business_role": [("manufacturer", "Nhà sản xuất"), ("importer", "Nhà nhập khẩu")],
        "object_kind": [("product", "Sản phẩm"), ("commercial_packaging", "Bao bì thương phẩm"), ("raw_material", "Nguyên liệu"), ("production_waste", "Chất thải sản xuất")],
        "product_group": [("bao_bi", "Bao bì"), ("ac_quy", "Ắc quy"), ("pin", "Pin"), ("dau_nhot", "Dầu nhớt"), ("sam_lop", "Săm lốp"), ("dien_tu", "Điện - điện tử"), ("phuong_tien", "Phương tiện")],
        "packaged_goods_category": [("thuc_pham", "Thực phẩm"), ("my_pham", "Mỹ phẩm"), ("thuoc", "Thuốc"), ("phan_bon_thuc_an_thu_y", "Phân bón/thức ăn chăn nuôi/thuốc thú y"), ("che_pham_tay_rua", "Chế phẩm tẩy rửa"), ("xi_mang", "Xi măng"), ("other", "Khác")],
        "market_placement": [("vietnam_market", "Đưa ra thị trường Việt Nam"), ("export_only", "Chỉ xuất khẩu"), ("temporary_import_reexport", "Tạm nhập - tái xuất")],
        "activity_purpose": [("commercial", "Kinh doanh thương mại"), ("research_study_test", "Nghiên cứu/học tập/thử nghiệm")],
        "reused_by_producer": [("yes", "Có"), ("no", "Không")],
    }
    result: list[CaseField] = []
    for key, label in CASE_FIELD_LABELS.items():
        if key not in required and key not in facts:
            continue
        kind = cast(
            Literal["text", "select", "number", "boolean"],
            "number" if key in {"annual_revenue_vnd", "recovery_rate"} else "select" if key in options else "text",
        )
        result.append(CaseField(
            key=key,
            label=label,
            kind=kind,
            options=[{"value": value, "label": option_label} for value, option_label in options.get(key, [])],
            required=key in required,
            missing=key in missing,
            value=_value(facts, key),
        ))
    return result


def legal_issues(facts: dict[str, FactValue], *, checklist: bool = False) -> list[LegalIssue]:
    issues = [
        LegalIssue(issue_id="actor", label="Đối tượng chịu trách nhiệm", query="Điều 77 khoản 1: nhà sản xuất, nhập khẩu chịu trách nhiệm", required_anchors=["Điều 77"], required_facts=["business_role"]),
        LegalIssue(issue_id="covered_object", label="Sản phẩm hoặc bao bì thuộc phạm vi", query="Điều 77 khoản 1, khoản 2 và Phụ lục XXII: đối tượng sản phẩm, bao bì", required_anchors=["Điều 77", "Phụ lục XXII"], required_facts=["object_kind", "product_group"]),
        LegalIssue(issue_id="market_scope", label="Đưa ra thị trường Việt Nam", query="Điều 77 khoản 1: đưa ra thị trường Việt Nam", required_anchors=["Điều 77"], required_facts=["market_placement"]),
        LegalIssue(issue_id="exemption", label="Trường hợp không phải thực hiện", query="Điều 77 khoản 3: xuất khẩu, nghiên cứu, doanh thu và thu hồi bao bì", required_anchors=["Điều 77"], required_facts=["activity_purpose"]),
        LegalIssue(issue_id="effective_date", label="Lộ trình áp dụng", query="Điều 77 khoản 4: lộ trình trách nhiệm tái chế", required_anchors=["Điều 77"], required_facts=[]),
    ]
    if checklist:
        issues.extend([
            LegalIssue(issue_id="recycling_rate", label="Tỷ lệ và quy cách tái chế", query="Điều 78 và Phụ lục XXII: tỷ lệ, quy cách tái chế", required_anchors=["Điều 78", "Phụ lục XXII"]),
            LegalIssue(issue_id="implementation", label="Hình thức thực hiện", query="Điều 79: hình thức thực hiện trách nhiệm tái chế", required_anchors=["Điều 79"]),
            LegalIssue(issue_id="reporting", label="Đăng ký và báo cáo", query="Điều 80: đăng ký kế hoạch và báo cáo kết quả", required_anchors=["Điều 80"]),
            LegalIssue(issue_id="financial", label="Đóng góp tài chính", query="Điều 81: đóng góp tài chính hỗ trợ tái chế", required_anchors=["Điều 81"]),
        ])
    return issues


def evaluate_assessment(facts: dict[str, FactValue], *, evidence_ids: dict[str, list[str]]) -> AssessmentResult:
    missing = missing_fact_keys(facts)
    if missing:
        return AssessmentResult(
            status=AssessmentStatus.NEEDS_INFORMATION,
            conclusion="Cần bổ sung thông tin trước khi có thể đánh giá nghĩa vụ EPR.",
            missing_facts=missing,
        )
    market = _value(facts, "market_placement")
    purpose = _value(facts, "activity_purpose")
    product_group = _value(facts, "product_group")
    category = _value(facts, "packaged_goods_category")
    try:
        revenue = int(_value(facts, "annual_revenue_vnd") or "0")
    except ValueError:
        revenue = 0
    exclusion = market in {"export_only", "temporary_import_reexport"} or purpose == "research_study_test"
    if product_group == "bao_bi" and category == "other":
        exclusion = True
    if product_group == "bao_bi" and revenue < 30_000_000_000:
        exclusion = True
    if _value(facts, "reused_by_producer") == "yes":
        # Article 77 refers to the rate in Appendix XXII.  A bare user-supplied
        # percentage is not enough: the applicable threshold must be read from
        # a provenance-verified Appendix row.  V4 therefore refuses to infer
        # an exemption from a made-up 100% threshold.
        return AssessmentResult(
            status=AssessmentStatus.CANNOT_DETERMINE,
            conclusion="Chưa thể xác định trường hợp thu hồi, tái sử dụng có thuộc diện loại trừ hay không.",
            assumptions=["Cần đối chiếu tỷ lệ áp dụng trong Phụ lục XXII với số liệu thu hồi của doanh nghiệp."],
        )
    if exclusion:
        return AssessmentResult(
            status=AssessmentStatus.LIKELY_OUT_OF_SCOPE,
            conclusion="Dựa trên facts đã xác nhận, trường hợp này có khả năng thuộc nhóm không phải thực hiện trách nhiệm tái chế.",
            reasons=[AssessmentReason(claim="Kết luận phụ thuộc vào trường hợp loại trừ tại Điều 77.", evidence_ids=evidence_ids.get("exemption", []))],
            assumptions=["Chỉ áp dụng cho facts do người dùng xác nhận."],
            next_steps=["Đối chiếu lại hồ sơ và bằng chứng cho trường hợp loại trừ."],
        )
    return AssessmentResult(
        status=AssessmentStatus.LIKELY_IN_SCOPE,
        conclusion="Dựa trên facts đã xác nhận, trường hợp này có khả năng thuộc phạm vi thực hiện trách nhiệm tái chế EPR.",
        reasons=[
            AssessmentReason(claim="Đối tượng, sản phẩm/bao bì và việc đưa ra thị trường cần được đối chiếu theo Điều 77 và Phụ lục XXII.", evidence_ids=evidence_ids.get("covered_object", []) + evidence_ids.get("market_scope", [])),
            AssessmentReason(claim="Lộ trình áp dụng cần được xác nhận theo nhóm sản phẩm/bao bì.", evidence_ids=evidence_ids.get("effective_date", [])),
        ],
        assumptions=["Kết quả là đánh giá sơ bộ theo facts người dùng xác nhận."],
        next_steps=["Đối chiếu tỷ lệ, quy cách tái chế và hình thức thực hiện theo tài liệu nguồn."],
    )


def follow_up_question(missing: list[str]) -> str:
    if not missing:
        return "Bạn có thể xác nhận thêm thông tin trường hợp này không?"
    key = missing[0]
    prompts = {
        "business_role": "Doanh nghiệp của bạn là nhà sản xuất hay nhà nhập khẩu chịu trách nhiệm về chất lượng và ghi nhãn?",
        "object_kind": "Đối tượng cần đánh giá là sản phẩm, bao bì thương phẩm, nguyên liệu hay chất thải phát sinh trong sản xuất?",
        "product_group": "Sản phẩm hoặc bao bì của bạn thuộc nhóm EPR nào?",
        "packaged_goods_category": "Bao bì này dùng để đóng gói nhóm hàng hóa nào, ví dụ thực phẩm, mỹ phẩm, thuốc, phân bón/thức ăn chăn nuôi/thuốc thú y, chất tẩy rửa hay xi măng?",
        "market_placement": "Sản phẩm hoặc bao bì này có được đưa ra thị trường Việt Nam, chỉ xuất khẩu hay tạm nhập–tái xuất?",
        "activity_purpose": "Hoạt động này nhằm kinh doanh thương mại hay chỉ phục vụ nghiên cứu, học tập hoặc thử nghiệm?",
        "annual_revenue_vnd": "Doanh thu bán các sản phẩm liên quan trong một năm là bao nhiêu?",
        "reused_by_producer": "Bao bì có được chính doanh nghiệp thu hồi, đóng gói lại và tiếp tục đưa ra thị trường không?",
        "recovery_rate": "Tỷ lệ thu hồi, đóng gói lại và tiếp tục đưa ra thị trường là bao nhiêu?",
    }
    return prompts.get(key, f"Bạn có thể bổ sung {CASE_FIELD_LABELS.get(key, key)} không?")
