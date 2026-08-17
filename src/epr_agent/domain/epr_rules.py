"""Deterministic EPR decision rules used by the V4 case routes.

The rule pack deliberately owns legal applicability.  An LLM may extract a
fact from a user message and explain an already-made decision; it never fills
unknown business facts or decides coverage from a similarity score.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, ClassVar, Literal, cast

from epr_agent.domain.v4 import (
    CASE_FIELD_LABELS,
    AssessmentReason,
    AssessmentResult,
    AssessmentStatus,
    CaseField,
    CaseFormState,
    FactConfirmationStatus,
    FactSource,
    FactValue,
    LegalIssue,
)


def _load_rule_pack() -> dict[str, object]:
    path = Path(__file__).resolve().parents[3] / "data" / "epr_rule_pack.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


_RULE_PACK = _load_rule_pack()


def _rule_section(name: str) -> dict[str, Any]:
    value = _RULE_PACK.get(name)
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


_THRESHOLDS = _rule_section("thresholds")
_EFFECTIVE_DATES = _rule_section("effective_dates")
_REQUIRED_FACTS = _rule_section("required_facts")
_EXCLUSIONS = _rule_section("exclusions")
EPR_RULE_PACK_VERSION = str(_RULE_PACK.get("rule_pack_version") or "epr-article-77-v3-manual-amendment-map")
EPR_RULE_ID = str(_RULE_PACK.get("rule_id") or "epr-article-77-current-law-v3")
PACKAGING_REVENUE_THRESHOLD_VND = int(_THRESHOLDS.get("packaging_revenue_exemption_vnd") or 30_000_000_000)
MAX_ANNUAL_REVENUE_VND = int(_THRESHOLDS.get("max_annual_revenue_vnd") or 10**15)
RECOVERY_RATE_MIN_PERCENT = float(_THRESHOLDS.get("recovery_rate_min_percent") or 0)
RECOVERY_RATE_MAX_PERCENT = float(_THRESHOLDS.get("recovery_rate_max_percent") or 100)


def _configured_values(key: str, fallback: tuple[str, ...]) -> set[str]:
    value = _EXCLUSIONS.get(key)
    if isinstance(value, list):
        return {str(item) for item in value}
    return set(fallback)


_EXPORT_EXCLUSIONS = _configured_values("market_placement", ("export_only", "temporary_import_reexport"))
_RESEARCH_EXCLUSIONS = _configured_values("activity_purpose", ("research_study_test",))
_UNRESOLVED_CATEGORIES = _configured_values("unresolved_packaged_categories", ("other",))
_UNRESOLVED_REUSE_VALUES = _configured_values("unresolved_reuse_values", ("yes",))
EPR_EFFECTIVE_DATES = {
    str(key): str(value)
    for key, value in _EFFECTIVE_DATES.items()
}

_ALLOWED_FACT_VALUES = {
    "business_role": {"manufacturer", "importer", "nhà sản xuất", "nhà nhập khẩu"},
    "object_kind": {"product", "commercial_packaging", "raw_material", "production_waste", "packaging"},
    "product_group": {"bao_bi", "ac_quy", "pin", "dau_nhot", "sam_lop", "dien_tu", "phuong_tien"},
    "packaged_goods_category": {"thuc_pham", "my_pham", "thuoc", "phan_bon_thuc_an_thu_y", "che_pham_tay_rua", "xi_mang", "other"},
    "material": {"plastic", "pet", "pe_pp", "paper", "glass", "metal", "rubber", "nhựa", "giấy", "kim loại", "cao su"},
    "market_placement": {"vietnam_market", "export_only", "temporary_import_reexport", "thị trường Việt Nam"},
    "activity_purpose": {"commercial", "research_study_test", "kinh doanh", "nghiên cứu", "học tập", "thử nghiệm"},
    "reused_by_producer": {"yes", "no", "có", "không"},
}

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

_CASE_FIELD_HELP_TEXT = {
    "business_role": "Chọn vai trò doanh nghiệp chịu trách nhiệm về sản phẩm hoặc bao bì.",
    "object_kind": "Xác định đối tượng đang được đánh giá.",
    "product_group": "Chọn nhóm sản phẩm hoặc bao bì thuộc phạm vi EPR.",
    "packaged_goods_category": "Chọn nhóm hàng hóa được đóng gói bên trong bao bì.",
    "material": "Chọn vật liệu chính hoặc quy cách cần đối chiếu.",
    "market_placement": "Cho biết sản phẩm có được đưa ra thị trường Việt Nam hay không.",
    "activity_purpose": "Chọn mục đích kinh doanh hoặc nghiên cứu, học tập, thử nghiệm.",
    "annual_revenue_vnd": "Nhập doanh thu bán sản phẩm liên quan trong một năm, tính bằng VNĐ.",
    "reused_by_producer": "Chỉ chọn Có nếu doanh nghiệp tự thu hồi và tiếp tục tái sử dụng bao bì.",
    "recovery_rate": "Nhập tỷ lệ thu hồi, đóng gói lại và tiếp tục đưa ra thị trường. Tỷ lệ này chưa tự thay thế căn cứ cần đối chiếu riêng.",
}


def _normalise(value: str) -> str:
    return " ".join((value or "").lower().split())


def _fact(value: str, source: FactSource, span: str, *, turn_id: str = "") -> FactValue:
    return FactValue(value=value, source=source, evidence_span=span, source_turn=turn_id, verified=False)


def extract_explicit_epr_facts(query: str, *, source: FactSource = FactSource.USER_TURN, turn_id: str = "") -> dict[str, FactValue]:
    """Extract only literal, visible user facts for the EPR rule pack."""

    text = _normalise(query)
    found: dict[str, FactValue] = {}
    if re.search(r"nhà\s*sản\s*xuất|sản\s*xuất|xưởng\s*(?:tôi|em|mình|chúng tôi)?\s*(?:làm|sản xuất|gia công|chế tạo)|nhà\s*máy\s*sản\s*xuất|cơ\s*sở\s*sản\s*xuất|tự\s*làm|tự\s*sản\s*xuất", text):
        found["business_role"] = _fact("manufacturer", source, "sản xuất", turn_id=turn_id)
    elif re.search(r"nhà\s*nhập\s*khẩu|nhập\s*khẩu|nhập\s*từ|nhập\s*về|nhập\s*hàng|mua\s*từ\s*nước\s*ngoài", text):
        found["business_role"] = _fact("importer", source, "nhập khẩu", turn_id=turn_id)

    if "nguyên liệu" in text:
        found["object_kind"] = _fact("raw_material", source, "nguyên liệu", turn_id=turn_id)
    elif "chất thải" in text or "phát sinh trong quá trình sản xuất" in text:
        found["object_kind"] = _fact("production_waste", source, "chất thải", turn_id=turn_id)
    elif any(p in text for p in ("bao bì", "hộp xốp", "túi ni-lông", "túi nilon", "túi bóng", "chai nhựa", "cốc nhựa", "ly nhựa", "hộp nhựa", "can nhựa", "thùng carton", "hộp giấy", "chai lọ")):
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
    for marker, material in (
        ("pet", "pet"), ("pe", "pe_pp"), ("pp", "pe_pp"),
        ("nhựa", "plastic"), ("hộp xốp", "plastic"), ("xốp", "plastic"), ("túi ni-lông", "plastic"), ("túi nilon", "plastic"),
        ("giấy", "paper"), ("thủy tinh", "glass"), ("kim loại", "metal"), ("cao su", "rubber"),
    ):
        if marker in text:
            found["material"] = _fact(material, source, marker, turn_id=turn_id)
            break

    if re.search(r"chỉ\s*xuất\s*khẩu|xuất\s*khẩu\s*toàn\s*bộ|chỉ\s*bán\s*ra\s*nước\s*ngoài", text):
        found["market_placement"] = _fact("export_only", source, "xuất khẩu", turn_id=turn_id)
    elif "tạm nhập" in text and "tái xuất" in text:
        found["market_placement"] = _fact("temporary_import_reexport", source, "tạm nhập tái xuất", turn_id=turn_id)
    elif any(marker in text for marker in ("đưa ra thị trường việt nam", "bán tại việt nam", "bán ở việt nam", "bán tại vn", "bán ở vn", "tại việt nam", "ở việt nam", "tại vn", "ở vn", "thị trường việt nam", "thị trường vn", "trong nước", "nội địa", "bán cho các chợ", "bán cho quán", "về vn", "về việt nam")):
        found["market_placement"] = _fact("vietnam_market", source, "thị trường Việt Nam", turn_id=turn_id)

    if any(marker in text for marker in ("nghiên cứu", "học tập", "thử nghiệm")):
        found["activity_purpose"] = _fact("research_study_test", source, "nghiên cứu/học tập/thử nghiệm", turn_id=turn_id)
    elif any(marker in text for marker in ("kinh doanh", "thương mại", "bán ra", "bán tại")):
        found["activity_purpose"] = _fact("commercial", source, "hoạt động thương mại", turn_id=turn_id)

    revenue = re.search(r"(?:doanh thu[^\d+\-]{0,40})?([-+]?\d+(?:[.,]\d+)?)\s*(tỷ|triệu)?\s*(?:đồng|vnđ|vnd)?", text)
    if revenue and ("doanh thu" in text or "tỷ" in text):
        amount = float(revenue.group(1).replace(",", "."))
        unit = revenue.group(2) or ""
        if unit == "tỷ":
            amount *= 1_000_000_000
        elif unit == "triệu":
            amount *= 1_000_000
        found["annual_revenue_vnd"] = _fact(
            str(int(amount)) if amount.is_integer() else str(amount),
            source,
            revenue.group(0),
            turn_id=turn_id,
        )
    if "không thu hồi" in text or "không tái sử dụng" in text:
        found["reused_by_producer"] = _fact("no", source, "không thu hồi", turn_id=turn_id)
    elif "thu hồi" in text and ("tái sử dụng" in text or "đóng gói lại" in text):
        found["reused_by_producer"] = _fact("yes", source, "thu hồi/tái sử dụng", turn_id=turn_id)
    return found


def _value(facts: dict[str, FactValue], key: str) -> str:
    item = facts.get(key)
    return item.value if item else ""


def validate_fact_value(key: str, value: str) -> str:
    """Normalize a decision-changing value or raise a field-level error.

    Returning an empty string for malformed input made an invalid number look
    identical to an intentionally cleared field. Empty is therefore reserved
    for an explicit delete; malformed values raise ``ValueError`` so callers
    can return a structured validation error.
    """

    cleaned = " ".join(str(value or "").split())
    if key == "annual_revenue_vnd" and cleaned:
        if not re.fullmatch(r"\d+", cleaned):
            raise ValueError("Doanh thu phải là số nguyên không âm, tính bằng VNĐ.")
        try:
            amount = int(cleaned)
        except ValueError:
            raise ValueError("Doanh thu không hợp lệ.") from None
        if amount < 0 or amount > MAX_ANNUAL_REVENUE_VND:
            raise ValueError("Doanh thu phải nằm trong khoảng 0 đến 1.000.000.000.000.000 VNĐ.")
        return cleaned
    if key == "recovery_rate" and cleaned:
        if not re.fullmatch(r"\d+(?:\.\d+)?", cleaned):
            raise ValueError("Tỷ lệ thu hồi phải là một số từ 0 đến 100.")
        rate = float(cleaned)
        if RECOVERY_RATE_MIN_PERCENT <= rate <= RECOVERY_RATE_MAX_PERCENT:
            return str(int(rate) if rate.is_integer() else rate)
        raise ValueError("Tỷ lệ thu hồi phải nằm trong khoảng 0–100%.")
    if key in _ALLOWED_FACT_VALUES and cleaned:
        if cleaned.casefold() not in {item.casefold() for item in _ALLOWED_FACT_VALUES[key]}:
            raise ValueError(f"Giá trị '{cleaned}' không nằm trong lựa chọn hợp lệ.")
        return cleaned
    return cleaned


def validate_case_facts(facts: dict[str, FactValue]) -> dict[str, str]:
    """Return field-level validation errors without changing user facts."""

    errors: dict[str, str] = {}
    for key, fact in facts.items():
        if not fact.value:
            continue
        try:
            validate_fact_value(key, fact.value)
        except ValueError as exc:
            errors[key] = str(exc)
    return errors


def required_fact_keys(facts: dict[str, FactValue]) -> list[str]:
    """Return decision-changing facts in the order the agent should ask them."""

    required = list(_REQUIRED_FACTS.get("base") or ["business_role", "object_kind", "product_group", "market_placement"])
    product_group = _value(facts, "product_group")
    market = _value(facts, "market_placement")
    if market not in _EXPORT_EXCLUSIONS:
        required.extend(str(item) for item in (_REQUIRED_FACTS.get("domestic_market") or ["activity_purpose"]))
    if product_group == "bao_bi":
        required.extend(str(item) for item in (_REQUIRED_FACTS.get("packaging") or ["packaged_goods_category"]))
        if market == "vietnam_market":
            required.extend(str(item) for item in (_REQUIRED_FACTS.get("packaging_domestic_market") or ["annual_revenue_vnd", "reused_by_producer"]))
            if _value(facts, "reused_by_producer") == "yes":
                required.extend(str(item) for item in (_REQUIRED_FACTS.get("packaging_reuse") or ["recovery_rate"]))
    return required


def missing_fact_keys(facts: dict[str, FactValue]) -> list[str]:
    return [key for key in required_fact_keys(facts) if not _value(facts, key)]


def submission_blocked_reason(facts: dict[str, FactValue]) -> str:
    """Explain why a complete form still cannot be submitted safely.

    These are valid user choices, not malformed values.  The current rule
    pack intentionally refuses to infer a legal outcome for them, so the form
    must not present a completed-count badge as if the next step were ready.
    Keeping this decision in the resolver prevents the frontend and runtime
    from maintaining separate copies of the same branch rules.
    """

    if _value(facts, "product_group") == "bao_bi" and _value(facts, "packaged_goods_category") in _UNRESOLVED_CATEGORIES:
        return "Nhóm hàng hóa “Khác” cần được đối chiếu với điều khoản cụ thể. Biểu mẫu hiện chưa thể tự kết luận cho lựa chọn này."
    if _value(facts, "reused_by_producer") in _UNRESOLVED_REUSE_VALUES:
        return "Trường hợp có thu hồi và tái sử dụng cần được đối chiếu thêm căn cứ riêng. Tỷ lệ bạn nhập chưa đủ để biểu mẫu tự kết luận."
    return ""


def case_fields(facts: dict[str, FactValue], missing: list[str]) -> list[CaseField]:
    required = set(required_fact_keys(facts))
    options = {
        "business_role": [("manufacturer", "Nhà sản xuất"), ("importer", "Nhà nhập khẩu")],
        "object_kind": [("product", "Sản phẩm"), ("commercial_packaging", "Bao bì thương phẩm"), ("raw_material", "Nguyên liệu"), ("production_waste", "Chất thải sản xuất")],
        "product_group": [("bao_bi", "Bao bì"), ("ac_quy", "Ắc quy"), ("pin", "Pin"), ("dau_nhot", "Dầu nhớt"), ("sam_lop", "Săm lốp"), ("dien_tu", "Điện - điện tử"), ("phuong_tien", "Phương tiện")],
        "packaged_goods_category": [("thuc_pham", "Thực phẩm"), ("my_pham", "Mỹ phẩm"), ("thuoc", "Thuốc"), ("phan_bon_thuc_an_thu_y", "Phân bón/thức ăn chăn nuôi/thuốc thú y"), ("che_pham_tay_rua", "Chế phẩm tẩy rửa"), ("xi_mang", "Xi măng"), ("other", "Khác")],
        "material": [("plastic", "Nhựa"), ("pet", "Nhựa PET"), ("pe_pp", "Nhựa PE/PP"), ("paper", "Giấy"), ("glass", "Thủy tinh"), ("metal", "Kim loại"), ("rubber", "Cao su")],
        "market_placement": [("vietnam_market", "Đưa ra thị trường Việt Nam"), ("export_only", "Chỉ xuất khẩu"), ("temporary_import_reexport", "Tạm nhập - tái xuất")],
        "activity_purpose": [("commercial", "Kinh doanh thương mại"), ("research_study_test", "Nghiên cứu/học tập/thử nghiệm")],
        "reused_by_producer": [("yes", "Có"), ("no", "Không")],
    }
    groups = {
        "business_role": "Doanh nghiệp",
        "object_kind": "Đối tượng",
        "product_group": "Đối tượng",
        "packaged_goods_category": "Đối tượng",
        "material": "Đối tượng",
        "market_placement": "Phạm vi hoạt động",
        "activity_purpose": "Phạm vi hoạt động",
        "annual_revenue_vnd": "Thông tin bổ sung",
        "reused_by_producer": "Thông tin bổ sung",
        "recovery_rate": "Thông tin bổ sung",
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
            group=groups.get(key, "Thông tin cần cung cấp"),
            display_order=len(result),
            kind=kind,
            options=[{"value": value, "label": option_label} for value, option_label in options.get(key, [])],
            required=key in required,
            importance="required" if key in required else "conditional" if key in {"packaged_goods_category", "annual_revenue_vnd", "reused_by_producer", "recovery_rate"} else "informational",
            missing=key in missing,
            value=_value(facts, key),
            help_text=_CASE_FIELD_HELP_TEXT.get(key, ""),
        ))
    return result


class CaseFormResolver:
    """Resolve one case draft consistently for API, session and V4 runtime."""

    FORM_VERSION = "case-form-v1"
    _TASK_TYPES: ClassVar[set[str]] = {"assess_epr_obligation", "build_compliance_checklist"}

    @staticmethod
    def _copy_facts(facts: dict[str, FactValue] | None) -> dict[str, FactValue]:
        return {
            str(key): value.model_copy(deep=True)
            for key, value in (facts or {}).items()
            if isinstance(value, FactValue)
        }

    @staticmethod
    def _update_value(
        key: str,
        raw: object,
    ) -> tuple[FactValue | None, bool]:
        """Return (fact, deleted) for a raw typed update."""

        if isinstance(raw, FactValue):
            value = raw.value
            confirmation = raw.confirmation_status
            source = raw.source
        elif isinstance(raw, dict):
            value = " ".join(str(raw.get("value") or "").split())
            try:
                confirmation = FactConfirmationStatus(
                    str(raw.get("confirmation_status") or FactConfirmationStatus.UNKNOWN.value)
                )
            except ValueError as exc:
                raise ValueError("Trạng thái xác nhận không hợp lệ.") from exc
            source = FactSource.CASE_PANEL
        else:
            value = " ".join(str(raw or "").split())
            confirmation = FactConfirmationStatus.USER_CONFIRMED
            source = FactSource.CASE_PANEL

        if not value:
            return None, True
        normalized = validate_fact_value(key, value)
        return FactValue(
            value=normalized,
            source=source,
            confidence=1.0,
            verified=False,
            confirmation_status=confirmation,
        ), False

    def resolve(
        self,
        task_type: str,
        facts: dict[str, FactValue] | None = None,
        fact_updates: dict[str, object] | None = None,
    ) -> CaseFormState:
        """Return a new form state without mutating input or persisting data."""

        if task_type not in self._TASK_TYPES:
            raise ValueError("Case form only supports assessment or checklist.")
        merged = self._copy_facts(facts)
        errors: dict[str, str] = {}
        for key, raw in (fact_updates or {}).items():
            field_key = str(key)
            if field_key not in CASE_FIELD_LABELS:
                errors[field_key] = "Thông tin này không thuộc biểu mẫu EPR hiện tại."
                continue
            try:
                value, deleted = self._update_value(field_key, raw)
            except ValueError as exc:
                errors[field_key] = str(exc)
                continue
            if deleted:
                merged.pop(field_key, None)
            elif value is not None:
                merged[field_key] = value

        # A parent selection invalidates facts that no longer belong to the
        # visible branch. This prevents a stale revenue/reuse value from
        # silently affecting a later assessment after the user changes the
        # product or market.
        if _value(merged, "product_group") != "bao_bi":
            for key in ("packaged_goods_category", "annual_revenue_vnd", "reused_by_producer", "recovery_rate"):
                merged.pop(key, None)
        elif _value(merged, "market_placement") != "vietnam_market":
            for key in ("annual_revenue_vnd", "reused_by_producer", "recovery_rate"):
                merged.pop(key, None)
        elif _value(merged, "reused_by_producer") != "yes":
            merged.pop("recovery_rate", None)

        errors.update({key: value for key, value in validate_case_facts(merged).items() if key not in errors})
        missing = missing_fact_keys(merged)
        fields = case_fields(merged, missing)
        for field in fields:
            if field.key in errors:
                field.missing = True
        required_fields = [field for field in fields if field.required]
        completed_count = sum(
            bool(merged.get(field.key) and merged[field.key].value and field.key not in errors)
            for field in required_fields
        )
        blocked_reason = submission_blocked_reason(merged)
        return CaseFormState(
            form_version=self.FORM_VERSION,
            task_type=cast(Any, task_type),
            status="ready" if not missing and not errors and not blocked_reason else "collecting",
            facts=merged,
            fields=fields,
            missing_facts=missing,
            validation_errors=errors,
            submission_blocked_reason=blocked_reason,
            completed_count=completed_count,
            required_count=len(required_fields),
        )

    def from_strings(
        self,
        task_type: str,
        facts: dict[str, FactValue] | None = None,
        updates: dict[str, str] | None = None,
    ) -> CaseFormState:
        typed_updates: dict[str, object] = {
            key: {"value": value, "confirmation_status": FactConfirmationStatus.USER_CONFIRMED.value}
            for key, value in (updates or {}).items()
        }
        return self.resolve(task_type, facts, typed_updates)


def legal_issues(facts: dict[str, FactValue], *, checklist: bool = False) -> list[LegalIssue]:
    raw_issues = _RULE_PACK.get("legal_issues")
    if isinstance(raw_issues, list):
        configured = [LegalIssue.model_validate(item) for item in raw_issues if isinstance(item, dict)]
        return configured if checklist else configured[:5]
    return []


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
    errors = validate_case_facts(facts)
    if errors:
        return AssessmentResult(
            status=AssessmentStatus.CANNOT_DETERMINE,
            conclusion="Chưa thể đánh giá vì một hoặc nhiều thông tin số chưa hợp lệ.",
            assumptions=["Giá trị doanh thu và tỷ lệ thu hồi phải được sửa trước khi đối chiếu quy định."],
        )
    revenue_text = _value(facts, "annual_revenue_vnd")
    revenue = int(revenue_text) if revenue_text else None
    exclusion = market in _EXPORT_EXCLUSIONS or purpose in _RESEARCH_EXCLUSIONS
    if product_group == "bao_bi" and category in _UNRESOLVED_CATEGORIES:
        return AssessmentResult(
            status=AssessmentStatus.CANNOT_DETERMINE,
            conclusion="Chưa thể xác định nhóm hàng hóa ‘khác’ có thuộc trường hợp được loại trừ hay không.",
            assumptions=["Cần xác định nhóm hàng hóa cụ thể hoặc cung cấp điều khoản đang áp dụng."],
        )
    if product_group == "bao_bi" and revenue is not None and revenue < PACKAGING_REVENUE_THRESHOLD_VND:
        exclusion = True
    if _value(facts, "reused_by_producer") in _UNRESOLVED_REUSE_VALUES:
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
            conclusion="Dựa trên các thông tin đã xác nhận, trường hợp này có khả năng thuộc diện miễn trừ thực hiện trách nhiệm tái chế.",
            reasons=[AssessmentReason(claim="Kết luận phụ thuộc vào quy định thuộc trường hợp loại trừ tại Điều 77.", evidence_ids=evidence_ids.get("exemption", []))],
            assumptions=[],
            next_steps=["Đối chiếu lại hồ sơ và bằng chứng cho trường hợp loại trừ."],
        )
    return AssessmentResult(
        status=AssessmentStatus.LIKELY_IN_SCOPE,
        conclusion="Dựa trên các thông tin đã xác nhận, trường hợp này thuộc phạm vi cần thực hiện trách nhiệm tái chế (EPR).",
        reasons=[
            AssessmentReason(claim="Đối tượng sản phẩm/bao bì đưa ra thị trường thuộc danh mục quy định tại Điều 77 và Phụ lục XXII.", evidence_ids=evidence_ids.get("covered_object", []) + evidence_ids.get("market_scope", [])),
            AssessmentReason(claim="Lộ trình áp dụng cần được xác nhận cụ thể theo nhóm sản phẩm/bao bì.", evidence_ids=evidence_ids.get("effective_date", [])),
        ],
        assumptions=[],
        next_steps=["Đối chiếu tỷ lệ, quy cách tái chế và hình thức thực hiện theo văn bản hướng dẫn."],
    )


def follow_up_question(missing: list[str]) -> str:
    if not missing:
        return "Bạn có thể xác nhận thêm thông tin trường hợp này không?"
    labels = [CASE_FIELD_LABELS.get(key, key) for key in missing]
    if len(missing) == 1:
        return f"Bạn còn thiếu 1 thông tin để tiếp tục. Hãy điền mục “{labels[0]}” trong biểu mẫu bên dưới."
    preview = ", ".join(labels[:3])
    suffix = " và các mục liên quan khác" if len(labels) > 3 else ""
    return f"Bạn còn thiếu {len(missing)} thông tin để tiếp tục, gồm {preview}{suffix}. Hãy hoàn thiện biểu mẫu bên dưới."
