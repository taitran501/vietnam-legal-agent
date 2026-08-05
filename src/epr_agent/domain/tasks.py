"""Task and case-fact interpretation for the bounded MVP.

This module is intentionally deterministic.  It gives the workflow a stable
contract for routing and required facts; an LLM may be added behind the same
contract later, but it cannot invent a new task or bypass missing-fact checks.
"""

from __future__ import annotations

import re
from typing import Any

from .models import TaskType

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
)

CHECKLIST_TERMS = (
    "checklist",
    "danh sách việc",
    "các bước",
    "cần làm gì",
    "hồ sơ cần",
    "lộ trình tuân thủ",
    "kế hoạch tuân thủ",
)

ASSESSMENT_TERMS = (
    "tôi có phải",
    "doanh nghiệp tôi",
    "công ty tôi",
    "có thuộc đối tượng",
    "có phải thực hiện",
    "có phải tuân thủ",
    "nghĩa vụ của tôi",
    "đánh giá nghĩa vụ",
    "xác định nghĩa vụ",
)

FACT_LABELS = {
    "business_role": "vai trò của doanh nghiệp (nhà sản xuất, nhà nhập khẩu hoặc vai trò khác)",
    "product_or_packaging": "loại sản phẩm hoặc bao bì",
    "material": "vật liệu chính",
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


def _normalise(text: str) -> str:
    return " ".join((text or "").lower().split())


def is_greeting(query: str) -> bool:
    q = _normalise(query)
    if not q:
        return False
    if any((re.search(rf"\b{re.escape(term)}\b", q) if len(term) <= 3 else term in q) for term in GREETING_TERMS):
        return True
    # Keep ordinary small talk out of legal retrieval when it contains no EPR
    # or legal signal.  This is deliberately conservative.
    return len(q) <= 45 and not any(term in q for term in EPR_TERMS) and any(
        term in q for term in ("thời tiết", "trời đẹp", "khỏe không", "đang làm gì")
    )


def is_epr_scope(query: str, history: list[dict[str, Any]] | None = None, active_case: dict[str, Any] | None = None) -> bool:
    text = " ".join(
        [_normalise(query)]
        + [_normalise(str(item.get("content", ""))) for item in (history or [])[-4:]]
    )
    if active_case and active_case.get("task_type") in {
        TaskType.ASSESS_EPR_OBLIGATION.value,
        TaskType.BUILD_COMPLIANCE_CHECKLIST.value,
    }:
        return True
    return any(term in text for term in EPR_TERMS)


def classify_task(query: str, history: list[dict[str, Any]] | None = None, active_case: dict[str, Any] | None = None) -> TaskType:
    q = _normalise(query)
    if is_greeting(q):
        return TaskType.CHITCHAT

    if any(term in q for term in CHECKLIST_TERMS):
        return TaskType.BUILD_COMPLIANCE_CHECKLIST

    # First-person/company-specific language signals a case assessment.  A
    # general question such as "đối tượng nào phải..." remains legal_lookup.
    if any(term in q for term in ASSESSMENT_TERMS) or re.search(r"\btôi\b|\bdoanh nghiệp\b|\bcông ty\b", q):
        return TaskType.ASSESS_EPR_OBLIGATION

    if active_case and active_case.get("task_type") in {
        TaskType.ASSESS_EPR_OBLIGATION.value,
        TaskType.BUILD_COMPLIANCE_CHECKLIST.value,
    } and len(q) < 100:
        return TaskType(active_case["task_type"])

    return TaskType.LEGAL_LOOKUP


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
    return facts


def merge_facts(active_case: dict[str, Any] | None, new_facts: dict[str, str]) -> dict[str, str]:
    merged = dict((active_case or {}).get("facts") or {})
    merged.update({key: value for key, value in new_facts.items() if value})
    return merged


def required_facts(task_type: TaskType) -> tuple[str, ...]:
    if task_type in {TaskType.ASSESS_EPR_OBLIGATION, TaskType.BUILD_COMPLIANCE_CHECKLIST}:
        return ("business_role", "product_or_packaging", "material")
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
    """

    q = " ".join((query or "").split())
    if not q:
        return q
    previous = latest_user_message(history)
    lower = _normalise(q)
    dependent = len(lower) <= 60 and (
        lower.startswith(("vậy", "thế", "còn", "nếu vậy", "trường hợp đó"))
        or any(token in lower for token in ("điều đó", "cái này", "việc này", "nó", "đó thì"))
    )
    if not previous or not dependent:
        return q

    facts = ", ".join(f"{key}={value}" for key, value in (active_case or {}).get("facts", {}).items())
    context = f" Cùng vụ việc hiện tại: {facts}." if facts else ""
    return f"Câu hỏi trước: {previous}. Câu hỏi tiếp theo: {q}.{context}"


def build_active_case(task_type: TaskType, facts: dict[str, str], query: str) -> dict[str, Any]:
    return {
        "task_type": task_type.value,
        "facts": dict(facts),
        "last_query": query,
    }
