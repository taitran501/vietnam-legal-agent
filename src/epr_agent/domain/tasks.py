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
    "nhà sản xuất",
    "nhập khẩu",
    "tái chế",
    "bao bì",
    "sản phẩm",
    "mức đóng góp",
    "quỹ bảo vệ môi trường",
    "nghị định 08",
    "nghị định 08/2022",
)

NON_EPR_SCOPE_TERMS = (
    "chứng khoán",
    "luật lao động",
    "hợp đồng lao động",
    "thuế thu nhập doanh nghiệp",
    "thuế doanh nghiệp",
    "luật đất đai",
    "quyền sử dụng đất",
)

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
)


def _normalise(text: str) -> str:
    return " ".join((text or "").lower().split())


def is_greeting(query: str) -> bool:
    q = _normalise(query)
    if not q:
        return False
    if any((re.search(rf"\b{re.escape(term)}\b", q) if len(term) <= 3 else term in q) for term in GREETING_TERMS):
        return True
    return len(q) <= 45 and not any(term in q for term in EPR_TERMS) and any(
        term in q for term in ("thời tiết", "trời đẹp", "khỏe không", "đang làm gì")
    )


def is_legal_scope(query: str, history: list[dict[str, Any]] | None = None, active_case: dict[str, Any] | None = None) -> bool:
    q = _normalise(query)
    return not any(term in q for term in NON_LEGAL_OUT_OF_SCOPE_TERMS)


def is_epr_scope(query: str, history: list[dict[str, Any]] | None = None, active_case: dict[str, Any] | None = None) -> bool:
    return is_legal_scope(query, history, active_case)


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

    # First-person/company-specific language signals a case assessment.  A
    # general question such as "đối tượng nào phải..." remains legal_lookup.
    if any(term in q for term in ASSESSMENT_TERMS) or (
        re.search(r"\btôi\b|\bdoanh nghiệp\b|\bcông ty\b", q) and any(t in q for t in EPR_TERMS)
    ):
        return TaskType.ASSESS_EPR_OBLIGATION

    if active_case and active_case.get("task_type") in {
        TaskType.ASSESS_EPR_OBLIGATION.value,
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
    if task_type in {TaskType.ASSESS_EPR_OBLIGATION, TaskType.BUILD_COMPLIANCE_CHECKLIST}:
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
    previous = latest_user_message(history)
    lower = _normalise(q)

    # --- Classic short-pronoun dependency ---
    short_dependent = len(lower) <= 60 and (
        lower.startswith(("vậy", "thế", "còn", "nếu vậy", "trường hợp đó"))
        or any(token in lower for token in ("điều đó", "cái này", "việc này", "nó", "đó thì"))
    )

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
        prev_lower = _normalise(previous)
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

    dependent = short_dependent or implicit_dependent
    if not previous or not dependent:
        return q

    facts = ", ".join(f"{key}={value}" for key, value in (active_case or {}).get("facts", {}).items())
    context = f" Cùng vụ việc hiện tại: {facts}." if facts else ""
    return preserve_explicit_anchors(q, f"Câu hỏi trước: {previous}. Câu hỏi tiếp theo: {q}.{context}")


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
    is_follow_up = standalone != " ".join((query or "").split())
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
