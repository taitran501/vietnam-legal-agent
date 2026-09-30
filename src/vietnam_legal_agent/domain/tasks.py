"""Task and case-fact interpretation shared across Vietnamese legal domains.

This module is intentionally deterministic.  It gives the workflow a stable
contract for routing and required facts; an LLM may be added behind the same
contract later, but it cannot invent a new task or bypass missing-fact checks.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from pydantic import BaseModel, Field, field_validator

from .legal import LegalAnchor, explicit_anchors
from .models import TaskType
from .routes import RouteType, route_for_task

# General legal topics used to recognise first-person/company requests as case
# assessments regardless of domain (labor, land, civil, corporate, traffic,
# marriage & family, environmental, tax, etc.).
CASE_TOPIC_TERMS = (
    "nghĩa vụ",
    "quyền",
    "trách nhiệm",
    "vi phạm",
    "bồi thường",
    "phạt",
    "hợp đồng",
    "lao động",
    "thử việc",
    "thôi việc",
    "sa thải",
    "chấm dứt",
    "lương",
    "thuê",
    "đặt cọc",
    "vay tiền",

    "hợp đồng vay",
    "ly hôn",
    "kết hôn",
    "cổ đông",
    "cổ phần",
    "đất",
    "sổ đỏ",
    "thu hồi",
    "giao thông",
    "nồng độ cồn",
    "môi trường",
    "bắt buộc",
    "đăng ký",
    "báo cáo",
    "chất thải",
    "ô nhiễm",
    "xả thải",
    "kiện",
    "đòi lại",
    "khiếu nại",
)

LEGAL_DOMAIN_SIGNALS: dict[str, tuple[str, ...]] = {
    "labor": ("lao động", "thử việc", "thôi việc", "sa thải", "đuổi việc", "nghỉ việc", "cho nghỉ việc", "bị cho nghỉ", "chấm dứt hợp đồng", "lương", "tiền lương", "người sử dụng lao động", "người lao động", "bảo hiểm xã hội", "bhtn", "bhyt", "bhxh", "bảo hiểm thất nghiệp", "làm thêm giờ", "thai sản", "giám đốc", "báo trước", "trợ cấp", "đền bù"),
    "civil_contract": ("hợp đồng", "thuê nhà", "chủ nhà", "tiền nhà", "đặt cọc", "tiền cọc", "vay tiền", "hợp đồng vay", "khoản vay", "cho vay", "mượn tiền", "đòi nợ", "mua bán", "tăng giá", "tăng giá thuê", "hợp đồng thuê", "lãi suất", "phạt vi phạm hợp đồng", "thừa kế", "di chúc", "bồi thường thiệt hại", "thiệt hại ngoài hợp đồng", "viện phí", "sửa xe"),
    "marriage_family": ("ly hôn", "kết hôn", "hôn nhân", "gia đình", "cấp dưỡng", "trích lục kết hôn", "quyền nuôi con", "nuôi con", "vợ chồng", "tài sản chung", "tài sản riêng", "chia tài sản", "phân chia tài sản", "chồng", "vợ", "bạo lực gia đình", "ngoại tình", "trước khi cưới"),
    "corporate": ("cổ đông", "cổ phần", "đại hội đồng", "hội đồng quản trị", "điều lệ công ty", "thành lập doanh nghiệp"),
    "land": ("đất", "đất đai", "sổ đỏ", "sổ hồng", "thu hồi đất", "bồi thường đất", "quyền sử dụng đất", "tái định cư", "giấy chứng nhận quyền sử dụng"),
    "traffic": ("giao thông", "nồng độ cồn", "vượt đèn", "quá tốc độ", "bằng lái", "tai nạn", "xử phạt giao thông", "mức phạt", "tai nạn giao thông", "viện phí", "sửa xe", "tông xe", "va chạm xe", "bồi thường tai nạn"),
    "tax": ("thuế", "thuế tncn", "thuế tndn", "thuế gtgt", "thuế vat", "giảm trừ gia cảnh", "người phụ thuộc", "hoàn thuế", "quyết toán thuế"),
    "intellectual_property": ("sở hữu trí tuệ", "nhãn hiệu", "bản quyền", "sáng chế", "kiểu dáng công nghiệp", "xâm phạm quyền"),
    "construction": ("xây dựng", "giấy phép xây dựng", "xây dựng trái phép", "công trình xây dựng", "nghiệm thu"),
    "consumer_protection": ("bảo vệ người tiêu dùng", "hàng giả", "hàng nhái", "khiếu nại người tiêu dùng"),
    "administrative": ("xử phạt vi phạm hành chính", "khiếu nại hành chính", "tố cáo", "tố tụng hành chính"),
    "environmental": ("môi trường", "chất thải", "ô nhiễm", "đánh giá tác động môi trường", "giấy phép môi trường"),
}


def detect_legal_domain(query: str) -> str:
    """Choose the most specific legal domain hinted by a query.

    Deterministic best-match over the supported domains.  Returns 'general'
    when no domain has a clear signal.  Used to pick the case engine for the
    closed V4 assessment path; it is a hint, not a hard gate.
    """
    q = _fold(query)
    best = "general"
    best_hits = 0
    for domain, signals in LEGAL_DOMAIN_SIGNALS.items():
        hits = sum(1 for signal in signals if _fold(signal) in q)
        if hits > best_hits:
            best, best_hits = domain, hits
    return best

NO_EVIDENCE_TERMS = (
    "chưa có trong corpus",
    "chưa có trong kho văn bản",
    "chưa được đề cập trong corpus",
    "chưa được đề cập trong văn bản",
    "ngoài phạm vi văn bản được cung cấp",
)

_GREETING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(xin\s+)?chao\b"),
    re.compile(r"\b(hello|hi|hey|alo)\b"),
    re.compile(r"\b(alo\s+)?ai\s+(vay|day|do|the|ha|nhi|dang\s+truc)\b"),
    re.compile(r"\b(ban|may|cau|em|anh|chi|bot|tro\s+ly)\s+la\s+ai\b"),
    re.compile(r"\b(ban|may|cau|em)\s+ten\s+gi\b"),
    re.compile(r"\bco\s+ai\s+(o\s+day\s+)?(khong|ko)\b"),
    re.compile(r"\b(lam\s+duoc\s+gi|giup\s+(duoc\s+)?gi|chuc\s+nang\s+la\s+gi|gioi\s+thieu)\b"),
    re.compile(r"\bgiup\s+(?:toi\s+)?(?:nhung\s+)?gi\b"),
    re.compile(r"\b(cam\s+on|thank|thanks|tam\s+biet|bye)\b"),
)

GREETING_TERMS = (
    "xin chào",
    "chào bạn",
    "hello",
    "hi",
    "alo",
    "cảm ơn",
    "thanks",
    "thank you",
    "tạm biệt",
    "chào buổi sáng",
    "chào buổi chiều",
    "chào buổi tối",
    "chào bot",
    "chào trợ lý",
    "chào em",
    "chào anh",
    "chào chị",
    "hey",
    "hôm nay trời",
    "hôm nay thế nào",
    "quan tâm nhất",
    "cần quan tâm",
    "quan tâm gì",
    "bắt đầu từ đâu",
    "bắt đầu thế nào",
    "làm được gì",
    "giúp gì được",
    "chức năng là gì",
    "hệ thống có những gì",
    "hướng dẫn tôi",
    "tư vấn giúp tôi",
    "cho tôi lời khuyên",
)

CHECKLIST_TERMS = (
    "checklist",
    "danh sách việc",
    "các bước",
    "cần làm gì",
    "hồ sơ cần",
    "danh sách hồ sơ",
    "cần chuẩn bị",
    "các việc cần",
    "lộ trình tuân thủ",
    "kế hoạch tuân thủ",
)

FACTUAL_LOOKUP_TERMS = (
    "quy định gì",
    "quy định thế nào",
    "có hiệu lực",
    "hiệu lực từ",
    "ban hành ngày",
    "ngày nào",
    "tối thiểu",
    "tối đa",
    "bao nhiêu",
    "mức phạt",
    "thời hạn",
    "điều kiện gì",
    "thủ tục gì",
    "là gì",
    "áp dụng từ",
    "cần bao nhiêu",
)

ASSESSMENT_TERMS = (
    "tôi có phải",
    "doanh nghiệp tôi",
    "công ty tôi",
    "nghĩa vụ của tôi",
    "đánh giá nghĩa vụ",
    "xác định nghĩa vụ",
)

GENERAL_LOOKUP_CUES = (
    "những nghĩa vụ nào",
    "nghĩa vụ nào",
    "căn cứ pháp lý ở đâu",
    "căn cứ ở đâu",
    "quy định ở điều nào",
    "được quy định ở điều nào",
    "điều nào quy định",
    "theo điều nào",
    "văn bản nào quy định",
)
EXPLICIT_ASSESSMENT_CUES = (
    "có phải",
    "có thuộc",
    "được hưởng",
    "được bồi thường",
    "có quyền",
    "vi phạm không",
    "đúng luật không",
    "đánh giá",
    "xác định",
    "tôi phải làm gì",
    "kiện",
)

PERSONAL_CONFLICT_CUES = (
    "bị",
    "không được",
    "không trả",
    "không thanh toán",
    "từ chối",
    "giữ lại",
    "giữ",
    "chậm trả",
    "đột ngột",
    "tranh chấp",
    "nợ",
    "ép buộc",
    "đơn phương",
    "không thực hiện",
    "gây thiệt hại",
)
PERSONAL_ADVICE_CUES = (
    "nên làm gì",
    "cần làm gì",
    "phải làm sao",
    "nên làm sao",
    "xử lý thế nào",
    "xử lý ra sao",
    "giải quyết thế nào",
    "giải quyết ra sao",
    "tôi nên",
    "tôi cần làm",
)

class ExtractedFacts(BaseModel):
    """A bounded, domain-neutral map of facts explicitly stated by the user."""

    values: dict[str, str] = Field(default_factory=dict)

    @field_validator("values", mode="before")
    @classmethod
    def _clean_values(cls, value: object) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        cleaned: dict[str, str] = {}
        for raw_key, raw_value in value.items():
            key = re.sub(r"[^\w -]", "", str(raw_key), flags=re.UNICODE).strip()[:60]
            item = " ".join(str(raw_value or "").split())[:240]
            if key and item:
                cleaned[key] = item
            if len(cleaned) >= 16:
                break
        return cleaned

    def compact(self) -> dict[str, str]:
        return dict(self.values)


class QueryPlan(BaseModel):
    """Validated structured result produced before the planner chooses a tool."""

    task_type: TaskType = TaskType.LEGAL_LOOKUP
    route: RouteType = RouteType.LEGAL_LOOKUP
    is_follow_up: bool = False
    standalone_query: str = ""
    retrieval_queries: list[str] = Field(default_factory=list)
    explicit_anchors: list[LegalAnchor] = Field(default_factory=list)
    legal_topics: list[str] = Field(default_factory=list)
    research_requested: bool = False
    facts: ExtractedFacts = Field(default_factory=ExtractedFacts)
    missing_facts: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    @field_validator("task_type", mode="before")
    @classmethod
    def _normalize_task_type(cls, value: object) -> object:
        val_str = str(value).lower()
        if val_str in {"case_assessment", "assess_case"}:
            return TaskType.CASE_ASSESSMENT
        if val_str in {"compliance_checklist", "checklist", "build_compliance_checklist"}:
            return TaskType.BUILD_COMPLIANCE_CHECKLIST
        if val_str in {"chitchat", "greeting"}:
            return TaskType.CHITCHAT
        if val_str in {"legal_lookup", "legal_explain_compare", "explain_compare", "out_of_scope", "research_web"}:
            return TaskType.LEGAL_LOOKUP
        return value

    @field_validator("route", mode="before")
    @classmethod
    def _normalize_route(cls, value: object) -> object:
        val_str = str(value).lower()
        if val_str in {"assess_case", "case_assessment"}:
            return RouteType.CASE_ASSESSMENT
        if val_str in {"compliance_checklist", "checklist", "build_compliance_checklist"}:
            return RouteType.COMPLIANCE_CHECKLIST
        if val_str in {"chitchat", "greeting"}:
            return RouteType.CHITCHAT
        if val_str in {"legal_explain_compare", "explain_compare"}:
            return RouteType.LEGAL_EXPLAIN_COMPARE
        if val_str in {"research_web", "web_research"}:
            return RouteType.RESEARCH_WEB
        if val_str in {"out_of_scope", "non_legal"}:
            return RouteType.OUT_OF_SCOPE
        return RouteType.LEGAL_LOOKUP

    @field_validator("standalone_query", mode="before")
    @classmethod
    def _clean_query(cls, value: object) -> str:
        return " ".join(str(value or "").split())[:3000]

    @field_validator("retrieval_queries", mode="before")
    @classmethod
    def _clean_retrieval_queries(cls, values: object) -> list[str]:
        if not isinstance(values, (list, tuple)):
            return []
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            query = " ".join(str(value or "").split())[:3000]
            key = query.casefold()
            if query and key not in seen:
                seen.add(key)
                cleaned.append(query)
            if len(cleaned) == 2:
                break
        return cleaned

    @field_validator("missing_facts")
    @classmethod
    def _do_not_require_intake_fields(cls, _values: list[str]) -> list[str]:
        # Ask for clarification in natural language when needed; never make a
        # fixed form a prerequisite for general legal retrieval.
        return []

    @field_validator("legal_topics")
    @classmethod
    def _clean_topics(cls, values: list[str]) -> list[str]:
        return [" ".join(str(value).split())[:120] for value in values if str(value).strip()][:8]


# The old name remains import-compatible for callers and persisted V2 tests.
# Runtime structured output and documentation use the more precise QueryPlan
# name: understanding creates a plan; it does not choose tools.
TaskUnderstanding = QueryPlan


NON_LEGAL_OUT_OF_SCOPE_TERMS = (
    "nấu ăn",
    "cách nấu",
    "món ăn",
    "phở bò",
    "bún chả",
    "bóng đá",
    "kết quả bóng đá",
    "ngoại hạng anh",
    "viết code",
    "lập trình",
    "thơ tình",
    "chơi game",
    "thời tiết ngày mai",
    "ignore all previous instructions",
    "ignore previous instructions",
    "coding assistant",
    "write code",
    "python code",
    "flask backend",
    "giá bitcoin",
    "bitcoin",
    "crypto",
    "tiền ảo",
)

LEGAL_SCOPE_TERMS = (
    "luật",
    "bộ luật",
    "pháp luật",
    "nghị định",
    "thông tư",
    "quyết định",
    "nghị quyết",
    "pháp lệnh",
    "văn bản",
    "quy định",
    "điều ",
    "khoản ",
    "điểm ",
    "hiệu lực",
    "nghĩa vụ",
    "trách nhiệm",
    "quyền lợi",
    "vi phạm",
    "bồi thường",
    "khởi kiện",
    "tranh chấp",
    "hợp đồng",
    "ly hôn",
    "sa thải",
    "thử việc",
    "cổ đông",
    "cổ phần",
    "đất đai",
    "sổ đỏ",
    "giao thông",
    "nồng độ cồn",
    "thời hạn",
    "mức phạt",
    "checklist",
    "tuân thủ",
    "chia tài sản",
    "tài sản chung",
    "tài sản riêng",
    "nuôi con",
    "viện phí",
    "sửa xe",
    "vợ chồng",
)

OWN_CONTEXT_TERMS = (
    "tôi",
    "mình",
    "chúng tôi",
    "công ty tôi",
    "công ty em",
    "doanh nghiệp tôi",
    "trường hợp của tôi",
    "trường hợp của em",
    "trường hợp của mình",
    "của công ty tôi",
    "của doanh nghiệp tôi",
    "hợp đồng của tôi",
    "hợp đồng của em",
)

CASE_ACTION_TERMS = (
    "có phải",
    "có thuộc",
    "phải thực hiện",
    "được hưởng",
    "bồi thường",
    "có quyền",
    "có nghĩa vụ",
    "đánh giá",
    "xác định",
    "kiểm tra nghĩa vụ",
    "áp dụng cho",
    "trường hợp",
    "tôi cần làm gì",
    "tôi phải làm gì",
    "tư vấn",
    "kiện",
    "đòi lại",
)


def _normalise(text: str) -> str:
    return " ".join((text or "").lower().split())


def _fold(text: str) -> str:
    """Compare informal Vietnamese without changing the original query."""

    normalized = unicodedata.normalize("NFD", _normalise(text))
    return "".join(char for char in normalized if not unicodedata.combining(char)).replace("đ", "d")


def _contains_any_term(text: str, terms: tuple[str, ...]) -> bool:
    folded = _fold(text)
    for term in terms:
        candidate = _fold(term)
        if len(candidate) <= 4:
            if re.search(rf"\b{re.escape(candidate)}\b", folded):
                return True
        elif candidate in folded:
            return True
    return False


def is_general_lookup_explanation_query(query: str) -> bool:
    """Recognize explicit requests for a general legal rule or its citation."""
    return _contains_any_term(query, GENERAL_LOOKUP_CUES) and not _contains_any_term(
        query,
        EXPLICIT_ASSESSMENT_CUES,
    )


def _contains_legal_signal(query: str) -> bool:
    q = _fold(query)
    if not q:
        return False
    if explicit_anchors(q):
        return True
    if _contains_any_term(q, LEGAL_SCOPE_TERMS):
        return True
    for signals in LEGAL_DOMAIN_SIGNALS.values():
        if _contains_any_term(q, signals):
            return True
    return False


def _is_factual_lookup_query(query: str) -> bool:
    q = _fold(query)
    for term in FACTUAL_LOOKUP_TERMS:
        folded_term = _fold(term)
        if len(folded_term) <= 6:
            if re.search(rf"\b{re.escape(folded_term)}\b", q):
                return True
        elif folded_term in q:
            return True
    return bool(
        explicit_anchors(q)
        or any(_fold(term) in q for term in ("cần tối thiểu", "từ ngày nào", "bao lâu", "thế nào"))
    )


def is_general_factual_lookup_query(query: str) -> bool:
    """Identify objective rule questions without overriding personal cases."""

    return _is_factual_lookup_query(query) and not _is_case_assessment_query(query)


def _is_case_assessment_query(query: str) -> bool:
    q = _fold(query)
    raw_q = _normalise(query)

    # Specific statutory penalty amount inquiries (e.g. "phạt bao nhiêu tiền", "mức phạt") remain factual lookups
    if _contains_any_term(q, ("phat bao nhieu", "muc phat", "phat tien bao nhieu", "bi phat bao nhieu")) and not _contains_any_term(q, ("boi thuong", "khoi kien", "tranh chap", "khieu nai", "tam giu phuong tien")):
        return False

    # Accent folding turns “tối” into the same token as “tôi”; preserve the
    # personal-pronoun boundary so a factual “tối đa” question cannot become a
    # case assessment. Accept both accented and keyboard-only “toi”.
    has_own_context = bool(re.search(r"(?<!\w)(?:tôi|toi|em|cháu|mình|minh)(?!\w)", raw_q)) or any(
        _fold(term) in q for term in OWN_CONTEXT_TERMS if term not in {"tôi", "mình"}
    )
    has_concrete_first_person_facts = bool(
        re.search(
            r"(?<!\w)(?:tôi|toi|em|cháu|mình|minh|chúng tôi)\s+"
            r"(?:là|đang|đã|bị|sản xuất|nhập khẩu|kinh doanh|bán|mua|thuê|ký|"
            r"nắm giữ|sở hữu|thừa kế|tranh chấp)\b",
            raw_q,
        )
    ) or any(
        _fold(term) in q for term in OWN_CONTEXT_TERMS if term not in {"tôi", "mình"}
    )
    # Real-life dispute / legality assessment without first-person pronoun:
    # e.g., "chủ nhà đòi tăng giá thuê nhà 30% có đúng luật không"
    has_legal_topic = (
        _contains_any_term(q, CASE_TOPIC_TERMS)
        or detect_legal_domain(query) != "general"
        or _contains_legal_signal(query)
    )
    if _contains_any_term(q, ("co dung luat khong", "co vi pham khong", "co duoc phep khong", "co hop phap khong", "xu ly the nao", "giai quyet the nao")) and has_legal_topic:
        return True

    if not has_own_context:
        return False
    if is_general_lookup_explanation_query(q):
        return False
    # Treat a user's concrete legal problem followed by a request for advice as
    # an assessment even when the wording does not match a fixed slot or form.
    # This also keeps personal disputes from being routed as generic checklists.
    if (
        has_legal_topic
        and _contains_any_term(q, PERSONAL_CONFLICT_CUES)
        and _contains_any_term(q, PERSONAL_ADVICE_CUES)
    ):
        return True
    if _contains_any_term(q, ASSESSMENT_TERMS):
        return True
    if _contains_any_term(q, CASE_ACTION_TERMS):
        return True
    # A first-person pronoun alone is not a case fact. Preserve concrete
    # descriptions the user actually gives, while leaving general modal and
    # rule questions on the ordinary legal-lookup route.
    return has_concrete_first_person_facts and _contains_any_term(q, CASE_TOPIC_TERMS)


def is_greeting(query: str) -> bool:
    q = _normalise(query)
    if not q:
        return False
    folded = _fold(q)
    is_greeting_match = any(pattern.search(folded) for pattern in _GREETING_PATTERNS) or any(
        (re.search(rf"\b{re.escape(_fold(term))}\b", folded) if len(term) <= 4 else _fold(term) in folded)
        for term in GREETING_TERMS
    )
    if is_greeting_match:
        if explicit_anchors(q):
            return False
        return not any(term in folded for term in ("tra cuu", "luat", "dieu ", "khoan ", "nghi dinh", "thong tu", "sa thai", "ly hon", "tranh chap", "khoi kien", "boi thuong"))
    return len(q) <= 45 and any(
        _fold(term) in folded for term in ("thời tiết", "trời đẹp", "khỏe không", "đang làm gì")
    )


def is_legal_scope(query: str, history: list[dict[str, Any]] | None = None, active_case: dict[str, Any] | None = None) -> bool:
    q = _normalise(query)
    return not _contains_any_term(q, NON_LEGAL_OUT_OF_SCOPE_TERMS)


def is_known_non_legal_query(query: str) -> bool:
    """Return true only for queries completely outside legal/regulatory scope."""
    return _contains_any_term(query, NON_LEGAL_OUT_OF_SCOPE_TERMS)


def has_explicit_no_evidence_signal(query: str) -> bool:
    """Detect a user assertion that the requested material is not in corpus."""

    q = _normalise(query)
    return any(term in q for term in NO_EVIDENCE_TERMS)


def classify_task(query: str, history: list[dict[str, Any]] | None = None, active_case: dict[str, Any] | None = None) -> TaskType:
    q = _normalise(query)
    if is_greeting(q):
        return TaskType.CHITCHAT
    # The current message (with context added only for a detected follow-up)
    # determines intent. A prior assessment must not capture unrelated turns.
    del history, active_case

    if _is_case_assessment_query(q):
        return TaskType.CASE_ASSESSMENT
    if _contains_any_term(q, CHECKLIST_TERMS):
        return TaskType.BUILD_COMPLIANCE_CHECKLIST
    # Generic corporate questions such as “công ty cổ phần cần tối thiểu bao
    # nhiêu…” remain factual legal lookups.
    if _is_factual_lookup_query(q):
        return TaskType.LEGAL_LOOKUP

    return TaskType.LEGAL_LOOKUP


def research_requested(query: str) -> bool:
    q = _normalise(query)
    has_search_action = _contains_any_term(q, ("tìm", "tra cứu", "tìm kiếm", "cập nhật"))
    has_external_source = _contains_any_term(
        q,
        (
            "web",
            "internet",
            "trên mạng",
            "nguồn công khai",
            "nguồn chính thức",
            "văn bản chính thức",
            "trang chính phủ",
            "cơ quan nhà nước",
            "mới nhất",
            "nguồn mới",
        ),
    )
    return has_search_action and has_external_source


def classify_route(
    query: str,
    history: list[dict[str, Any]] | None = None,
    active_case: dict[str, Any] | None = None,
) -> RouteType:
    """Choose a product route while preserving legacy task type compatibility across all Vietnamese laws."""

    if research_requested(query):
        return RouteType.RESEARCH_WEB
    if is_greeting(query):
        return RouteType.CHITCHAT
    if is_known_non_legal_query(query):
        return RouteType.OUT_OF_SCOPE
    if not is_legal_scope(query, history, active_case):
        return RouteType.OUT_OF_SCOPE
    task = classify_task(query, history, active_case)
    if task != TaskType.LEGAL_LOOKUP:
        return route_for_task(task)
    q = _normalise(query)
    if any(term in q for term in ("giải thích", "so sánh", "khác nhau", "khác gì", "phân biệt", "tóm tắt điều")):
        return RouteType.LEGAL_EXPLAIN_COMPARE
    return RouteType.LEGAL_LOOKUP


def extract_facts(query: str) -> dict[str, str]:
    """Do not infer typed slots from keywords; the original query is context."""
    del query
    return {}


def merge_facts(active_case: dict[str, Any] | None, new_facts: dict[str, str]) -> dict[str, str]:
    merged = dict((active_case or {}).get("facts") or {})
    merged.update({key: value for key, value in new_facts.items() if value})
    return merged


def required_facts(task_type: TaskType) -> tuple[str, ...]:
    del task_type
    return ()


def missing_facts(task_type: TaskType, facts: dict[str, str]) -> list[str]:
    del task_type, facts
    return []


def build_follow_up_question(task_type: TaskType, missing: list[str]) -> str:
    if not missing:
        return ""
    first_missing = "một chi tiết liên quan trong tình huống"
    if task_type == TaskType.BUILD_COMPLIANCE_CHECKLIST:
        return f"Để lập danh sách đúng trường hợp, trước hết bạn cho biết {first_missing} nhé. Nếu cần thêm thông tin, mình sẽ hỏi tiếp."
    return f"Để đánh giá chính xác, trước hết bạn cho biết {first_missing} nhé. Nếu cần thêm thông tin, mình sẽ hỏi tiếp."


def latest_user_message(history: list[dict[str, Any]] | None) -> str:
    for item in reversed(history or []):
        if item.get("role") == "user":
            return str(item.get("content", ""))
    return ""


def latest_conversation_turn(
    history: list[dict[str, Any]] | None,
) -> tuple[str, str, dict[str, Any]]:
    """Return the latest user/assistant exchange without trusting its prose.

    Durable history is stored as alternating user and assistant messages.  A
    follow-up needs both sides: the previous user turn establishes the topic,
    while the previous assistant metadata identifies which sources were already
    shown.  The assistant text is only used as quoted retrieval context; it is
    never treated as legal evidence.
    """

    items = list(history or [])
    user_index = next(
        (index for index in range(len(items) - 1, -1, -1) if items[index].get("role") == "user"),
        None,
    )
    if user_index is None:
        return "", "", {}
    previous_user = str(items[user_index].get("content") or "")
    previous_assistant = ""
    assistant_metadata: dict[str, Any] = {}
    for item in items[user_index + 1 :]:
        if item.get("role") == "user":
            break
        if item.get("role") == "assistant":
            previous_assistant = str(item.get("content") or "")
            raw_metadata = item.get("metadata")
            if isinstance(raw_metadata, dict):
                assistant_metadata = dict(raw_metadata)
            break
    return previous_user, previous_assistant, assistant_metadata


def latest_turn_requires_context(history: list[dict[str, Any]] | None) -> bool:
    """Whether the last assistant turn explicitly left the legal question open.

    A vague follow-up cannot turn an unresolved answer into new legal evidence.
    Persisted termination metadata is the source of truth; answer wording and
    domain-specific vocabulary are deliberately not inspected.
    """

    _previous_user, previous_answer, metadata = latest_conversation_turn(history)
    if not previous_answer:
        return False
    return str(metadata.get("termination_reason") or "") in {
        "awaiting_user_input",
        "insufficient_evidence",
        "citation_verification_failed",
    }


def is_context_dependent_query(query: str) -> bool:
    """Detect a terse/elliptical query that cannot stand alone safely."""

    lower = _normalise(query)
    if not lower:
        return False
    # A complete instrument number identifies a retrievable subject by itself.
    # Keep article-only prompts (for example, "còn Điều 78?") dependent because
    # the governing document still comes from the preceding turn.  Enumeration
    # prompts such as "còn Luật số ... nào khác?" remain dependent as well.
    full_document_anchor = any(anchor.document_number for anchor in explicit_anchors(query)) or bool(
        re.search(r"\bluật\s+(?:số\s*)?\d+/\d{4}/[a-z0-9đ-]+", lower)
    )
    asks_for_more = _contains_any_term(lower, ("gì", "nào", "nữa", "thêm", "khác"))
    if lower.startswith("còn") and full_document_anchor and not asks_for_more:
        return False
    # A demonstrative can refer to an event described earlier in this same
    # message. That makes the message self-contained; it is not a request to
    # recover missing context from a previous turn.
    folded_query = _fold(lower)
    for reference in ("việc này", "điều đó", "cái này", "nó", "đó thì"):
        folded_reference = _fold(reference)
        match = re.search(rf"(?<!\w){re.escape(folded_reference)}(?!\w)", folded_query)
        if match and match.start() > 0:
            antecedent = folded_query[: match.start()].strip(" ,;:.!?\n")
            if antecedent and _contains_legal_signal(antecedent):
                return False
    dependent_reference = _contains_any_term(folded_query, ("điều đó", "cái này", "việc này", "nó", "đó thì"))
    dependent_opener = any(
        re.match(rf"^{re.escape(opener)}(?:$|\W)", lower)
        for opener in ("vậy", "thế", "còn", "nếu vậy", "trường hợp đó")
    )
    return len(lower) <= 60 and (
        dependent_opener
        or dependent_reference
    )


def _source_context(metadata: dict[str, Any]) -> str:
    """Extract bounded source identifiers from a prior assistant message."""

    values: list[str] = []
    raw_sources = metadata.get("sources")
    if isinstance(raw_sources, list):
        for item in raw_sources:
            if not isinstance(item, dict):
                continue
            for key in ("instrument_number", "source_id", "title", "anchor", "official_url"):
                value = " ".join(str(item.get(key) or "").split())
                if value and value not in values:
                    values.append(value)
    raw_citations = metadata.get("citations")
    if isinstance(raw_citations, list):
        for item in raw_citations:
            if not isinstance(item, dict):
                continue
            for key in ("label", "document_id"):
                value = " ".join(str(item.get(key) or "").split())
                if value and value not in values:
                    values.append(value)
    return "; ".join(values[:12])


def rewrite_follow_up(query: str, history: list[dict[str, Any]] | None, active_case: dict[str, Any] | None) -> str:
    """Make a dependent follow-up retrievable without pretending to be memory.

    This is a deterministic baseline for multi-turn query rewriting.  It uses
    only the recent conversation and active case facts; the durable history is
    still stored separately and is not copied into the retrieval query wholesale.

    Detection heuristic (either condition triggers context injection):
    - Short pronouns/particles (≤ 60 chars): "vậy", "thế", "còn", pronoun tokens.
    - Implicit numeric/entity reference (≤ 180 chars): query references a number
      or key noun that appeared in the previous bot/user message and the query
      begins with a conditional/interrogative opener signalling dependency.
    """

    q = " ".join((query or "").split())
    if not q:
        return q
    previous, previous_answer, assistant_metadata = latest_conversation_turn(history)
    lower = _normalise(q)

    # --- Classic short-pronoun dependency ---
    short_dependent = is_context_dependent_query(q) and len(lower) <= 60

    # --- Implicit reference: numeric or domain-noun anchored follow-up ---
    # Catches queries like "nếu hết 60 ngày mà bạn ấy không đạt..." after
    # a prior answer mentioning "60 ngày" without explicit pronoun.
    implicit_dependent = False
    if not short_dependent and previous and 20 < len(lower) <= 180:
        # Opener tokens that signal the query builds on prior context
        conditional_openers = (
            "nếu", "nếu như", "vậy nếu", "còn nếu", "trường hợp", "thế còn",
            "tiếp theo", "sau đó", "sau khi", "thêm", "ngoài ra", "hơn nữa", "thế thì",
            "ủa", "ờ thì", "thế mà", "mà", "nhưng", "vậy thì", "ok vậy",
            "tiện thể", "tiện đây", "theo đó", "như vậy",
            "mình", "tôi", "chúng tôi", "bêm", "chúng mình",
            "cuối năm", "lúc đó", "khi đó", "trước khi",
        )
        starts_with_conditional = any(lower.startswith(op) for op in conditional_openers)
        # Check if a key number from bot's last reply appears in this query
        prev_lower = _normalise(f"{previous} {previous_answer}")
        numbers_in_prev = re.findall(r"\b\d+\b", prev_lower)
        query_numbers = re.findall(r"\b\d+\b", lower)
        shares_number = bool(set(numbers_in_prev) & set(query_numbers))
        # Key domain nouns that signal topic continuity without full self-description
        continuity_nouns = (
            "bạn ấy", "bạn đó", "người đó", "họ", "anh ấy", "chị ấy",
            "mảnh đất", "mảnh đó", "đất đó", "thửa đất",
            "xưởng", "công ty", "doanh nghiệp", "cơ sở",
            "hợp đồng", "hợp đồng đó", "thời hạn đó", "mức đó",
            "di chúc", "thừa kế", "tài sản", "tài sản đó",
            "bằng lái", "giấy phép", "nhãn hiệu", "bản quyền",
            "nhà", "chủ nhà", "người thuê", "phòng", "phòng trọ",
            "tiệm", "quán", "cửa hàng", "shop",
            "đăng ký", "giấy chứng nhận", "hồ sơ",
            "thuế", "thuế tncn", "bảo hiểm", "bhxh",
            "hóa đơn", "kế toán", "quyết toán",
        )
        has_continuity_noun = any(noun in lower for noun in continuity_nouns)
        implicit_dependent = starts_with_conditional and (shares_number or has_continuity_noun)

    # A short continuation can omit the usual "còn/vậy" marker, for example
    # "có nghị định nào không" after a turn about new 2026 laws.  Require a
    # prior legal/year signal so a standalone question with the same wording
    # is not forced into clarification.
    continuation_question = bool(
        previous
        and len(lower) <= 120
        and lower.startswith(("có ", "văn bản ", "luật ", "nghị định "))
        and any(token in lower for token in ("nào", "không", "nữa"))
        and (
            bool(re.search(r"\b(?:19|20)\d{2}\b", _normalise(f"{previous} {previous_answer}")))
            or any(term in _normalise(f"{previous} {previous_answer}") for term in ("luật", "nghị định", "quy định", "điều"))
        )
    )

    dependent = short_dependent or implicit_dependent or continuation_question
    if not previous or not dependent:
        return q

    facts = ", ".join(f"{key}={value}" for key, value in (active_case or {}).get("facts", {}).items())
    context = f" Cùng vụ việc hiện tại: {facts}." if facts else ""
    source_context = _source_context(assistant_metadata)
    answer_context = " ".join(previous_answer.split())[:720].rstrip(".。!?！？ ")
    prior_answer = f" Câu trả lời trước (chỉ là ngữ cảnh, phải kiểm tra lại): {answer_context}." if answer_context else ""
    prior_sources = (
        f" Các nguồn đã nêu trước đó, không coi là bằng chứng mới: {source_context}."
        if source_context
        else ""
    )
    additional = (
        " Hãy tìm các văn bản/quy định khác với những mục đã nêu trước đó."
        if lower.startswith(("còn", "thêm", "ngoài ra", "hơn nữa"))
        else ""
    )
    rewritten = (
        f"Chủ đề từ lượt trước: {previous}.{prior_answer}{prior_sources} "
        f"Yêu cầu tiếp theo: {q}.{additional}{context}"
    )
    return preserve_explicit_anchors(q, rewritten)


def preserve_explicit_anchors(original_query: str, rewritten_query: str) -> str:
    """Ensure rewriting cannot silently remove a named source or legal anchor."""

    rewritten = " ".join((rewritten_query or "").split())
    missing = [
        value
        for anchor in explicit_anchors(original_query)
        for value in (
            anchor.document_number,
            anchor.document_title,
            anchor.article,
            anchor.clause,
            anchor.point,
            anchor.appendix,
        )
        if value and value.casefold() not in rewritten.casefold()
    ]
    if missing:
        rewritten = f"{rewritten} Tham chiếu gốc: {', '.join(dict.fromkeys(missing))}."
    return rewritten


def build_active_case(task_type: TaskType, facts: dict[str, str], query: str) -> dict[str, Any]:
    return {
        "task_type": task_type.value,
        "facts": dict(facts),
        "missing_facts": missing_facts(task_type, facts),
        "last_query": query,
    }


def deterministic_task_understanding(
    query: str,
    history: list[dict[str, Any]] | None,
    active_case: dict[str, Any] | None,
) -> TaskUnderstanding:
    """Safe fallback when a structured model is unavailable or invalid.

    This fallback never expands the allowed task/action surface and is kept for
    outage handling and deterministic tests, not as the production decision
    mechanism.
    """

    task = classify_task(query, history, active_case)
    standalone = rewrite_follow_up(query, history, active_case)
    facts = merge_facts(active_case, extract_facts(query))
    is_follow_up = is_context_dependent_query(query) or standalone != " ".join((query or "").split()) or bool(active_case)
    return TaskUnderstanding(
        task_type=task,
        route=classify_route(query, history, active_case),
        is_follow_up=is_follow_up,
        standalone_query=standalone,
        explicit_anchors=explicit_anchors(query),
        legal_topics=[],
        research_requested=research_requested(query),
        facts=ExtractedFacts(values=facts),
        missing_facts=missing_facts(task, facts),
        confidence=0.5,
    )
