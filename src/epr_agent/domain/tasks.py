"""Task and case-fact interpretation for the bounded MVP.

This module is intentionally deterministic.  It gives the workflow a stable
contract for routing and required facts; an LLM may be added behind the same
contract later, but it cannot invent a new task or bypass missing-fact checks.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, field_validator

from .legal import LegalAnchor, explicit_anchors
from .models import TaskType
from .routes import RouteType, route_for_task

EPR_TERMS = (
    "epr",
    "trách nhiệm mở rộng",
    "tái chế",
    "bao bì",
    "mức đóng góp",
    "quỹ bảo vệ môi trường",
    "nghị định 08",
    "nghị định 08/2022",
    "đóng góp tài chính",
)

# General legal topics used to recognise first-person/company requests as case
# assessments regardless of domain (labor, land, civil, corporate, traffic,
# marriage & family, environmental/EPR).
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
    "vay",
    "ly hôn",
    "kết hôn",
    "cổ đông",
    "cổ phần",
    "đất",
    "sổ đỏ",
    "thu hồi",
    "giao thông",
    "nồng độ cồn",
    "tái chế",
    "bao bì",
    "môi trường",
    "epr",
    "sản xuất",
    "nhập khẩu",
    "thực hiện",
    "bắt buộc",
    "đăng ký",
    "báo cáo",
    "đóng góp",
    "mức đóng góp",
)

LEGAL_DOMAIN_SIGNALS: dict[str, tuple[str, ...]] = {
    "labor": ("lao động", "thử việc", "thôi việc", "sa thải", "chấm dứt hợp đồng", "lương", "người sử dụng lao động", "người lao động", "bảo hiểm xã hội", "làm thêm giờ", "thai sản"),
    "civil_contract": ("hợp đồng", "thuê nhà", "đặt cọc", "vay", "mua bán", "tăng giá thuê", "lãi suất", "phạt vi phạm hợp đồng"),
    "marriage_family": ("ly hôn", "kết hôn", "hôn nhân", "gia đình", "cấp dưỡng", "trích lục kết hôn"),
    "corporate": ("cổ đông", "cổ phần", "đại hội đồng", "hội đồng quản trị", "điều lệ công ty", "thành lập doanh nghiệp"),
    "land": ("đất", "đất đai", "sổ đỏ", "sổ hồng", "thu hồi", "thu hồi đất", "bồi thường đất", "quyền sử dụng đất", "tái định cư", "giấy chứng nhận quyền sử dụng"),
    "traffic": ("giao thông", "nồng độ cồn", "vượt đèn", "quá tốc độ", "bằng lái", "tai nạn", "xử phạt giao thông", "mức phạt"),
    "epr": EPR_TERMS
    + (
        "pin",
        "ắc quy",
        "săm lốp",
        "dầu nhớt",
        "sản phẩm điện",
        "điện tử",
        "tái sử dụng",
        "thu hồi để tái chế",
        "môi trường",
    ),
}


def detect_legal_domain(query: str) -> str:
    """Choose the most specific legal domain hinted by a query.

    Deterministic best-match over the supported domains.  Returns 'general'
    when no domain has a clear signal.  Used to pick the case engine for the
    closed V4 assessment path; it is a hint, not a hard gate.
    """
    q = _normalise(query)
    best = "general"
    best_hits = 0
    for domain, signals in LEGAL_DOMAIN_SIGNALS.items():
        hits = sum(1 for signal in signals if signal in q)
        if hits > best_hits:
            best, best_hits = domain, hits
    return best

NO_EVIDENCE_TERMS = (
    "chưa có trong corpus",
    "chưa có trong kho văn bản",
    "chưa được đề cập trong corpus",
    "chưa được đề cập trong văn bản",
    "ngoài nghị định 08",
    "epr của eu",
    "epr của châu âu",
    "epr tại thái lan",
    "epr ở thái lan",
    "tiêu chuẩn quốc tế epr",
)

GREETING_TERMS = (
    "xin chào",
    "chào bạn",
    "hello",
    "hi",
    "cảm ơn",
    "thanks",
    "thank you",
    "tạm biệt",
    "bạn là ai",
    "hôm nay trời",
    "hôm nay thế nào",
    "chào buổi sáng",
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

FACT_LABELS = {
    "business_role": "vai trò của doanh nghiệp (nhà sản xuất, nhà nhập khẩu hoặc vai trò khác)",
    "product_or_packaging": "loại sản phẩm hoặc bao bì",
    "material": "vật liệu chính",
    "activity_scope": "phạm vi hoạt động (ví dụ: thị trường Việt Nam, xuất khẩu, hoặc cả hai)",
}

_ROLE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"nhà\s*sản\s*xuất|sản\s*xuất", "nhà sản xuất"),
    (r"nhà\s*nhập\s*khẩu|nhập\s*khẩu", "nhà nhập khẩu"),
    (r"phân\s*phối", "nhà phân phối"),
    (r"bán\s*lẻ", "đơn vị bán lẻ"),
)

_PRODUCT_TERMS = (
    "bao bì",
    "chai",
    "lon",
    "sản phẩm điện",
    "ắc quy",
    "pin",
    "dầu nhớt",
    "săm lốp",
    "lốp",
)

_MATERIAL_TERMS = (
    "nhựa",
    "giấy",
    "kim loại",
    "thủy tinh",
    "cao su",
    "gỗ",
    "hỗn hợp",
)

_ACTIVITY_SCOPE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"chỉ\s*xuất\s*khẩu|xuất\s*khẩu\s*toàn\s*bộ", "chỉ xuất khẩu"),
    (r"nội\s*địa|tại\s*việt\s*nam|ở\s*việt\s*nam|thị\s*trường\s*việt\s*nam", "thị trường Việt Nam"),
    (r"cả\s*nội\s*địa\s*(và|lẫn)\s*xuất\s*khẩu|nội\s*địa\s*và\s*xuất\s*khẩu", "nội địa và xuất khẩu"),
)


class ExtractedFacts(BaseModel):
    """Only explicit facts are accepted from a model or deterministic parser."""

    business_role: str = ""
    product_or_packaging: str = ""
    material: str = ""
    activity_scope: str = ""

    @field_validator("business_role", "product_or_packaging", "material", "activity_scope", mode="before")
    @classmethod
    def _clean_value(cls, value: object) -> str:
        return " ".join(str(value or "").split())[:160]

    def compact(self) -> dict[str, str]:
        return {key: value for key, value in self.model_dump().items() if value}


class QueryPlan(BaseModel):
    """Validated structured result produced before the planner chooses a tool."""

    task_type: TaskType = TaskType.LEGAL_LOOKUP
    route: RouteType = RouteType.LEGAL_LOOKUP
    is_follow_up: bool = False
    standalone_query: str = ""
    explicit_anchors: list[LegalAnchor] = Field(default_factory=list)
    legal_topics: list[str] = Field(default_factory=list)
    research_requested: bool = False
    facts: ExtractedFacts = Field(default_factory=ExtractedFacts)
    missing_facts: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("standalone_query", mode="before")
    @classmethod
    def _clean_query(cls, value: object) -> str:
        return " ".join(str(value or "").split())[:3000]

    @field_validator("missing_facts")
    @classmethod
    def _allow_known_fact_keys(cls, values: list[str]) -> list[str]:
        return [value for value in values if value in FACT_LABELS]

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
    "tái chế",
    "bao bì",
    "epr",
    "thời hạn",
    "mức phạt",
    "checklist",
    "tuân thủ",
)

OWN_CONTEXT_TERMS = (
    "tôi",
    "mình",
    "chúng tôi",
    "công ty tôi",
    "doanh nghiệp tôi",
    "trường hợp của tôi",
    "của công ty tôi",
    "của doanh nghiệp tôi",
    "hợp đồng của tôi",
)

CASE_ACTION_TERMS = (
    "có phải",
    "có thuộc",
    "phải thực hiện",
    "được hưởng",
    "có quyền",
    "có nghĩa vụ",
    "đánh giá",
    "xác định",
    "áp dụng cho",
    "trường hợp",
    "tôi cần làm gì",
    "tôi phải làm gì",
)


def _normalise(text: str) -> str:
    return " ".join((text or "").lower().split())


def _contains_legal_signal(query: str) -> bool:
    q = _normalise(query)
    if not q:
        return False
    if explicit_anchors(q):
        return True
    if any(term in q for term in LEGAL_SCOPE_TERMS):
        return True
    return any(term in q for signals in LEGAL_DOMAIN_SIGNALS.values() for term in signals)


def _is_factual_lookup_query(query: str) -> bool:
    q = _normalise(query)
    return bool(
        explicit_anchors(q)
        or any(term in q for term in FACTUAL_LOOKUP_TERMS)
        or any(term in q for term in ("cần tối thiểu", "từ ngày nào", "bao lâu", "thế nào"))
    )


def _is_case_assessment_query(query: str) -> bool:
    q = _normalise(query)
    has_own_context = any(term in q for term in OWN_CONTEXT_TERMS)
    # EPR has an established business-role phrasing where “doanh nghiệp
    # nhập khẩu/sản xuất ... có phải ...” is already a concrete case request,
    # even when the user omits “tôi”.
    if (
        any(term in q for term in ("doanh nghiệp", "nhà sản xuất", "nhà nhập khẩu"))
        and any(term in q for term in EPR_TERMS)
        and any(term in q for term in CASE_ACTION_TERMS)
    ):
        return True
    if not has_own_context:
        return False
    if any(term in q for term in ASSESSMENT_TERMS):
        return True
    if any(term in q for term in CASE_ACTION_TERMS):
        return True
    # Preserve natural first-person fact descriptions such as “tôi là nhà
    # sản xuất bao bì” without treating a generic “công ty cổ phần” question
    # as a case assessment.
    return any(term in q for term in CASE_TOPIC_TERMS)


def is_greeting(query: str) -> bool:
    q = _normalise(query)
    if not q:
        return False
    # A greeting followed by a legal request is a legal query, not chitchat.
    if _contains_legal_signal(q):
        return False
    if any((re.search(rf"\b{re.escape(term)}\b", q) if len(term) <= 3 else term in q) for term in GREETING_TERMS):
        return True
    return len(q) <= 45 and not any(term in q for term in EPR_TERMS) and any(
        term in q for term in ("thời tiết", "trời đẹp", "khỏe không", "đang làm gì")
    )


def is_legal_scope(query: str, history: list[dict[str, Any]] | None = None, active_case: dict[str, Any] | None = None) -> bool:
    q = _normalise(query)
    if any(term in q for term in NON_LEGAL_OUT_OF_SCOPE_TERMS):
        return False
    if active_case:
        return True
    # A terse context-only prompt is still a legal workflow boundary even
    # before history is available; the planner will ask the user to restate
    # the missing topic instead of calling retrieval.
    if is_context_dependent_query(q):
        return True
    return _contains_legal_signal(q)


def is_known_non_epr_query(query: str) -> bool:
    """Return true only for queries completely outside legal/regulatory scope."""
    q = _normalise(query)
    return any(term in q for term in NON_LEGAL_OUT_OF_SCOPE_TERMS)


def has_explicit_no_evidence_signal(query: str) -> bool:
    """Detect a user assertion that the requested material is not in corpus."""

    q = _normalise(query)
    return any(term in q for term in NO_EVIDENCE_TERMS)


def classify_task(query: str, history: list[dict[str, Any]] | None = None, active_case: dict[str, Any] | None = None) -> TaskType:
    q = _normalise(query)
    if is_greeting(q):
        return TaskType.CHITCHAT

    if any(term in q for term in CHECKLIST_TERMS):
        return TaskType.BUILD_COMPLIANCE_CHECKLIST

    # A case assessment requires ownership of a concrete situation.  Generic
    # corporate questions such as “công ty cổ phần cần tối thiểu bao nhiêu…”
    # remain factual legal lookups.
    if _is_factual_lookup_query(q) and not _is_case_assessment_query(q):
        return TaskType.LEGAL_LOOKUP
    if _is_case_assessment_query(q):
        return TaskType.CASE_ASSESSMENT

    if active_case and active_case.get("task_type") in {
        TaskType.CASE_ASSESSMENT.value,
        TaskType.BUILD_COMPLIANCE_CHECKLIST.value,
    } and len(q) < 100:
        return TaskType(active_case["task_type"])

    return TaskType.LEGAL_LOOKUP


def research_requested(query: str) -> bool:
    q = _normalise(query)
    return any(term in q for term in ("tìm trên web", "tìm web", "nguồn công khai", "tra cứu internet", "tìm nguồn mới"))


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
    if is_known_non_epr_query(query):
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
    """Extract only explicit case facts; do not infer missing values."""

    q = _normalise(query)
    facts: dict[str, str] = {}
    for pattern, value in _ROLE_PATTERNS:
        if re.search(pattern, q):
            facts["business_role"] = value
            break

    for value in _PRODUCT_TERMS:
        if value in q:
            facts["product_or_packaging"] = value
            break

    for value in _MATERIAL_TERMS:
        if value in q:
            facts["material"] = value
            break
    for pattern, value in _ACTIVITY_SCOPE_PATTERNS:
        if re.search(pattern, q):
            facts["activity_scope"] = value
            break
    return facts


def merge_facts(active_case: dict[str, Any] | None, new_facts: dict[str, str]) -> dict[str, str]:
    merged = dict((active_case or {}).get("facts") or {})
    merged.update({key: value for key, value in new_facts.items() if value})
    return merged


def required_facts(task_type: TaskType) -> tuple[str, ...]:
    if task_type in {TaskType.CASE_ASSESSMENT, TaskType.BUILD_COMPLIANCE_CHECKLIST}:
        return ("business_role", "product_or_packaging", "material", "activity_scope")
    return ()


def missing_facts(task_type: TaskType, facts: dict[str, str]) -> list[str]:
    return [name for name in required_facts(task_type) if not facts.get(name)]


def build_follow_up_question(task_type: TaskType, missing: list[str]) -> str:
    if not missing:
        return ""
    labels = [FACT_LABELS[name] for name in missing if name in FACT_LABELS]
    joined = "; ".join(labels)
    if task_type == TaskType.BUILD_COMPLIANCE_CHECKLIST:
        return f"Để lập checklist đúng trường hợp, bạn cho biết thêm {joined} được không?"
    return f"Để đánh giá nghĩa vụ chính xác, bạn cho biết thêm {joined} được không?"


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
    asks_for_more = any(token in lower for token in ("gì", "nào", "nữa", "thêm", "khác"))
    if lower.startswith("còn") and full_document_anchor and not asks_for_more:
        return False
    return len(lower) <= 60 and (
        lower.startswith(("vậy", "thế", "còn", "nếu vậy", "trường hợp đó"))
        or any(token in lower for token in ("điều đó", "cái này", "việc này", "nó", "đó thì"))
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
        for value in (anchor.document_number, anchor.article, anchor.clause, anchor.point)
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
    is_follow_up = is_context_dependent_query(query) or standalone != " ".join((query or "").split())
    return TaskUnderstanding(
        task_type=task,
        route=classify_route(query, history, active_case),
        is_follow_up=is_follow_up,
        standalone_query=standalone,
        explicit_anchors=explicit_anchors(query),
        legal_topics=[],
        research_requested=research_requested(query),
        facts=ExtractedFacts(**facts),
        missing_facts=missing_facts(task, facts),
        confidence=0.5,
    )
