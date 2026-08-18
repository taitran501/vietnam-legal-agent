"""
Query routing — compatibility 2-way classification: "epr_query" | "chitchat"

Design principle:
  This compatibility router separates conversational noise (chitchat) from
  substantive legal questions that should hit the corpus.
  "Out of domain" is NOT a router concern — it is a corpus concern:
    - If Qdrant finds relevant docs → legal answer
    - If Qdrant finds nothing (score too low) → the configured official-source
      fallback may handle the request.
  The legacy `epr_query` label is retained for API and test compatibility.

Uses gpt-4o-mini with Structured Outputs (strict schema).
NOTE: gpt-3.5-turbo only supports JSON mode — not strict Structured Outputs.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from backend.config import get_settings
from backend.core.llm_instances import get_llm_router

# ---------------------------------------------------------------------------
# 2-way router: epr_query | chitchat
# ---------------------------------------------------------------------------

class _QueryRoute(BaseModel):
    datasource: Literal["epr_query", "chitchat"] = Field(
        ...,
        description=(
            "'epr_query' for any substantive legal question (the legacy label "
            "is retained while the corpus and web fallback handle the domain). "
            "'chitchat' ONLY for pure social interaction: greetings, thanks, "
            "farewells, identity questions, gibberish."
        ),
    )


_ROUTER_SYSTEM = """Bạn là bộ lọc đầu vào cho Trợ lý Pháp luật Việt Nam.

Phân loại câu hỏi vào ĐÚNG MỘT trong 2 nhóm:

**epr_query** — Bất kỳ câu hỏi tra cứu hoặc tư vấn pháp lý thực sự nào (Đất đai, Lao động, Dân sự, Doanh nghiệp, Thuế, Môi trường/EPR, Giao thông, Hành chính...).
  → Chọn nhóm này cho mọi câu hỏi cần đối chiếu pháp luật hoặc giải đáp tình huống.

**chitchat** — CHỈ chọn khi câu hỏi là giao tiếp xã giao thuần túy:
  - Lời chào hỏi: "xin chào", "hello", "hi"
  - Cảm ơn, tạm biệt: "cảm ơn", "bye", "tạm biệt"
  - Hỏi danh tính trợ lý: "bạn là ai", "bạn tên gì", "bạn làm được gì", "bạn giúp được gì"
  - Chuỗi ký tự vô nghĩa: "asdf", "123abc", spam."""

_router_prompt = ChatPromptTemplate.from_messages([
    ("system", _ROUTER_SYSTEM),
    ("human", "{question}"),
])


_LEGAL_HINT_PATTERNS = (
    r"\bdieu\s+\d+\b",
    r"\bkhoan\s+\d+\b",
    r"\bchuong\s+[ivxlcdm\d]+\b",
    r"\bmuc\s+\d+\b",
)

_LEGAL_HINT_KEYWORDS = (
    "epr",
    "trach nhiem mo rong",
    "nha san xuat",
    "tai che",
    "bao bi",
    "nghi dinh",
    "luat",
    "quy bao ve moi truong",
    "muc dong gop",
    "phu luc",
)

_CHITCHAT_EXACT = {
    "hi",
    "hello",
    "hey",
    "xin chao",
    "chao",
    "chao ban",
    "cam on",
    "thanks",
    "thank you",
    "bye",
    "tam biet",
    "ban la ai",
    "ban ten gi",
}

_CHITCHAT_PHRASES = (
    "cam on",
    "tam biet",
    "ban la ai",
    "ban ten gi",
    "ban co the lam gi",
    "ban lam duoc gi",
    "hom nay troi",
)


def _normalize_vi(text: str) -> str:
    lowered = (text or "").strip().lower()
    normalized = unicodedata.normalize("NFD", lowered)
    normalized = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    normalized = normalized.replace("đ", "d")
    return " ".join(normalized.split())


def _fast_route_query(question: str) -> Literal["epr_query", "chitchat"] | None:
    """Cheap deterministic routing path to avoid unnecessary LLM calls."""
    q_raw = (question or "").strip()
    if not q_raw:
        return "chitchat"
    q = _normalize_vi(q_raw)

    if q in _CHITCHAT_EXACT:
        return "chitchat"

    if any(phrase in q for phrase in _CHITCHAT_PHRASES):
        return "chitchat"

    if any(re.search(pattern, q) for pattern in _LEGAL_HINT_PATTERNS):
        return "epr_query"

    if any(keyword in q for keyword in _LEGAL_HINT_KEYWORDS):
        return "epr_query"

    # Reject obvious keyboard-noise strings without sending them through legal
    # retrieval. This stays deliberately narrow so ordinary English queries do
    # not become false chitchat matches.
    ascii_letters = re.findall(r"[a-z]", q)
    if len(ascii_letters) >= 8 and not re.search(r"\s", q):
        vowel_ratio = sum(letter in "aeiou" for letter in ascii_letters) / len(ascii_letters)
        if vowel_ratio < 0.25:
            return "chitchat"

    # Very short non-informational utterances.
    if len(q) <= 6 and re.search(r"[a-zA-ZÀ-ỹ]", q):
        return "chitchat"

    return None


def _get_router():
    return _router_prompt | get_llm_router().with_structured_output(_QueryRoute)


def route_query(question: str) -> Literal["epr_query", "chitchat"]:
    """Route chitchat versus substantive legal work using the legacy label."""
    fast_route = _fast_route_query(question)
    if fast_route:
        return fast_route

    settings = get_settings()
    if not settings.enable_llm_router_fallback:
        # Speed-first default: uncertain queries go to substantive retrieval path.
        return "epr_query"

    result = _get_router().invoke({"question": question})
    ds = result.get("datasource") if isinstance(result, dict) else getattr(result, "datasource", None)
    return ds or "epr_query"


# ---------------------------------------------------------------------------
# Law router
# ---------------------------------------------------------------------------

class _LawRoute(BaseModel):
    datasource: Literal["vectorstore", "chitchat"] = Field(
        ...,
        description="'vectorstore' for legal document queries, 'chitchat' otherwise",
    )


_LAW_ROUTER_SYSTEM = """Bạn là chuyên gia phân loại câu hỏi pháp luật.

Nguồn dữ liệu:
1. **vectorstore** – tra cứu điều luật, nghị định, quy định pháp luật cụ thể.
2. **chitchat** – giao tiếp thân thiện, không liên quan pháp luật.

Ưu tiên **vectorstore** nếu câu hỏi về Điều/Chương/Mục/Nghị định/Luật cụ thể.
Ưu tiên **chitchat** nếu chỉ là câu chào hỏi hoặc câu hỏi chung chung không liên quan."""

_law_router_prompt = ChatPromptTemplate.from_messages([
    ("system", _LAW_ROUTER_SYSTEM),
    ("human", "{question}"),
])


def _get_law_router():
    return _law_router_prompt | get_llm_router().with_structured_output(_LawRoute)


def route_law(question: str) -> Literal["vectorstore", "chitchat"]:
    result = _get_law_router().invoke({"question": question})
    ds = result.get("datasource") if isinstance(result, dict) else getattr(result, "datasource", None)
    return ds or "vectorstore"
