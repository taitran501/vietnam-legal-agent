"""
Generation, grading, and web-search utilities.

Public API
----------
format_docs(docs)                     → str
generate_legal(question, docs)        → str
chitchat_response(question, history)  → str
web_fallback(question)                → str
stream_faq_answer(query, faq_doc)     → AsyncIterator[str]
stream_legal_answer(query, docs)      → AsyncIterator[str]
"""

from __future__ import annotations

import json as _json_module
import logging
import os
import re
import warnings
from collections.abc import AsyncIterator

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel

from backend.config import get_settings
from backend.core.llm_instances import get_llm_fast, get_llm_router, get_llm_smart, get_llm_stream

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chunk_text(content: object) -> str:
    """Normalize LangChain text chunks without leaking structured block reprs."""

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    return ""

def _truncate(text: str, max_tokens: int = 800) -> str:
    """Rough character-based truncation (≈4 chars per token)."""
    max_chars = max_tokens * 4
    return text[:max_chars] + "…" if len(text) > max_chars else text


def _citation_segment(kind: str, raw: object) -> str | None:
    """Build one segment for the [label] line; avoid 'Điều Điều 126' when Dieu is already a full heading."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    low = s.lower()
    if kind == "dieu":
        return s if low.startswith("điều") else f"Điều {s}"
    if kind == "chuong":
        return s if low.startswith("chương") else f"Chương {s}"
    if kind == "muc":
        return s if low.startswith("mục") else f"Mục {s}"
    return s


def _meta_heading(name_key: str, fallback_key: str, meta: dict) -> str:
    """Prefer explicit *Name fields; else use Dieu/Chuong/Muc text from index (law.json stores full headings there)."""
    named = (meta.get(name_key) or "").strip()
    if named and named.upper() != "N/A":
        return named
    fb = (meta.get(fallback_key) or "").strip()
    return fb if fb else "N/A"


def format_docs(
    docs: list[Document],
    max_docs: int | None = None,
    max_tokens_per_doc: int | None = None,
) -> str:
    """Format a list of documents for LLM context, including metadata."""
    if not docs:
        return "Không có tài liệu liên quan."

    settings = get_settings()
    if max_docs is None:
        max_docs = max(1, settings.legal_context_max_docs)
    if max_tokens_per_doc is None:
        max_tokens_per_doc = max(128, settings.legal_context_max_tokens_per_doc)

    law_label = (settings.law_citation_label or "").strip()
    header = ""
    if law_label:
        header = (
            "Tên văn bản pháp luật đầy đủ (ghi nguyên văn sau mỗi dòng trong mục "
            f'\"📚 Nguồn tham khảo:\", không được rút gọn): {law_label}\n\n'
        )

    parts: list[str] = []
    for i, doc in enumerate(docs[:max_docs], 1):
        meta = doc.metadata
        citations: list[str] = []
        seg = _citation_segment("dieu", meta.get("Dieu"))
        if seg:
            citations.append(seg)
        seg = _citation_segment("muc", meta.get("Muc"))
        if seg:
            citations.append(seg)
        seg = _citation_segment("chuong", meta.get("Chuong"))
        if seg:
            citations.append(seg)
        label = ", ".join(citations) if citations else f"Tài liệu {i}"

        dieu_heading = _meta_heading("Dieu_Name", "Dieu", meta)
        chuong_heading = _meta_heading("Chuong_Name", "Chuong", meta)
        muc_heading = _meta_heading("Muc_Name", "Muc", meta)

        content = _truncate(doc.page_content, max_tokens_per_doc)
        ref_line = (
            f"Dòng chuẩn cho Nguồn tham khảo [tương ứng chỉ số inline]: "
            f"{dieu_heading} — {law_label}"
            if law_label and dieu_heading != "N/A"
            else ""
        )
        ref_block = f"{ref_line}\n" if ref_line else ""

        parts.append(
            f"[{label}]\n"
            f"Tên Điều: {dieu_heading}\n"
            f"Tên Chương: {chuong_heading}\n"
            f"Tên Mục: {muc_heading}\n"
            f"{ref_block}"
            f"Nội dung:\n{content}"
        )

    return header + "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# LLM relevance gate — fast binary check before expensive generation
# ---------------------------------------------------------------------------

class _RelevanceVerdict(BaseModel):
    relevant: bool


_RELEVANCE_GATE_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "Bạn là bộ lọc relevance. Chỉ trả lời TRUE hoặc FALSE.",
    ),
    (
        "human",
        """Tài liệu pháp luật được truy xuất:
{doc_snippet}

Câu hỏi của người dùng: {question}

Tài liệu này có chứa thông tin để trả lời câu hỏi không?
- TRUE: nội dung tài liệu khớp với chủ đề câu hỏi, có thể dùng để trả lời
- FALSE: câu hỏi về chủ đề hoàn toàn khác với nội dung tài liệu""",
    ),
])


def is_retrieval_relevant(question: str, docs: list[Document]) -> bool:
    """Binary relevance check: do the retrieved docs actually answer the question?

    Uses gpt-4o-mini structured output. The snippet passed to the gate includes
    the article metadata (Dieu, Chuong) as the strongest domain signal — a query
    about 'thị trường chứng khoán' against a doc labelled 'Điều 77. Trách nhiệm
    tái chế' should clearly return FALSE without ambiguity.
    """
    if not docs:
        return False
    try:
        meta = docs[0].metadata
        dieu_label = meta.get("Dieu", "")
        chuong_label = meta.get("Chuong", "")
        text_snippet = docs[0].page_content[:150]
        # Include metadata labels as the primary signal; they are decisive for
        # determining domain match (e.g. "Điều 77. Tái chế" vs "chứng khoán")
        snippet = f"[{dieu_label}][{chuong_label}]\n{text_snippet}"

        chain = _RELEVANCE_GATE_PROMPT | get_llm_router().with_structured_output(_RelevanceVerdict)
        result = chain.invoke({"question": question, "doc_snippet": snippet})
        relevant = result.get("relevant") if isinstance(result, dict) else getattr(result, "relevant", False)
        return bool(relevant)
    except Exception:
        logger.warning("Legal relevance gate failed; stopping before generation", exc_info=True)
        return False


def check_legal_evidence(
    docs: list[Document],
    *,
    min_docs: int = 1,
    min_chars: int = 160,
) -> tuple[bool, str]:
    """Lightweight evidence guardrail before legal generation.

    Returns:
        (is_sufficient, reason)
    """
    if len(docs) < max(min_docs, 1):
        return False, "not_enough_docs"

    top_docs = docs[:3]
    total_chars = sum(len((d.page_content or "").strip()) for d in top_docs)
    if total_chars < max(min_chars, 1):
        return False, "content_too_short"

    has_legal_metadata = any(
        bool((d.metadata or {}).get("Dieu") or (d.metadata or {}).get("Chuong") or (d.metadata or {}).get("Muc"))
        for d in top_docs
    )
    if not has_legal_metadata:
        return False, "missing_legal_metadata"

    return True, "ok"


# ---------------------------------------------------------------------------
# Follow-up suggestion generator
# ---------------------------------------------------------------------------

# Keywords that indicate a vague follow-up (user asking "what else" without specifics)
# These are phrases that ask for "more" without a specific topic
_VAGUE_FOLLOWUP_PHRASES = [
    "còn gì nữa", "còn nữa không", "còn nữa", "có thêm", "nữa không",
    "còn luật nào", "còn điều nào", "còn gì khác", "còn cái nào",
    "what else", "anything else", "any other", "more laws", "more about",
    "có gì nữa", "nữa đi", "nào khác",
]

# Patterns that indicate a SPECIFIC request (NOT vague)
_SPECIFIC_PATTERNS = [
    r"điều\s+\d+",           # "điều 77", "điều 54"
    r"chương\s+\d+",         # "chương 6"
    r"mục\s+\d+",            # "mục 3"
    r"nghị định\s+\d+",      # "nghị định 08"
    r"luật\s+bảo vệ",        # "luật bảo vệ môi trường"
    r"thông tư\s+\d+",       # "thông tư 02"
    r"phụ lục",              # "phụ lục XXII"
    r"tỷ lệ",                # "tỷ lệ tái chế"
    r"đối tượng",            # "đối tượng phải"
    r"nghĩa vụ",             # "nghĩa vụ của"
    r"quyền",                # "quyền lợi"
    r"mức đóng",             # "mức đóng góp"
    r"bao bì",               # "bao bì nhựa"
    r"ắc quy",               # "ắc quy"
    r"dầu nhớt",             # "dầu nhớt"
    r"săm lốp",              # "săm lốp"
    r"tái chế",              # "tái chế"
    r"tỷ lệ",                # "tỷ lệ"
]


def _is_vague_followup(question: str, chat_history: str = "") -> bool:
    """
    Detect if a question is a vague follow-up like 'còn nữa không', 'what else'.

    A vague follow-up is one that asks for "more" without specifying a concrete topic.
    """
    q = question.lower().strip()

    # Must be short (vague follow-ups are typically brief)
    if len(q) > 50:
        return False

    # Must NOT contain specific legal references
    has_specific = any(re.search(p, q) for p in _SPECIFIC_PATTERNS)
    if has_specific:
        return False

    # Must contain a vague follow-up phrase
    has_vague = any(kw in q for kw in _VAGUE_FOLLOWUP_PHRASES)

    return has_vague


_VAGUE_FOLLOWUP_RESPONSE = """Bạn hỏi về các văn bản khác, nhưng tôi cần biết cụ thể hơn để hỗ trợ tốt nhất.

Hiện tại tôi có thể tư vấn về:
- **Nghị định 08/2022/NĐ-CP** — Chi tiết trách nhiệm tái chế, tỷ lệ bắt buộc, đối tượng thực hiện
- **Luật Bảo vệ Môi trường 2020** — Khung pháp lý tổng quát về EPR (Điều 54-55)
- **Thông tư 02/2022/TT-BTNMT** — Hướng dẫn thực hiện chi tiết
- **Phụ lục XXII** — Tỷ lệ tái chế bắt buộc theo từng loại sản phẩm

Bạn muốn tìm hiểu về vấn đề cụ thể nào? Ví dụ:
- "Tỷ lệ tái chế bắt buộc là bao nhiêu?"
- "Đối tượng nào phải thực hiện EPR?"
- "Nghĩa vụ của nhà sản xuất bao gồm những gì?"
"""


def get_vague_followup_response() -> str:
    """Return a structured response for vague follow-ups."""
    return _VAGUE_FOLLOWUP_RESPONSE


# ---------------------------------------------------------------------------
# Follow-up suggestion generator — suggests 3 related questions
# ---------------------------------------------------------------------------

_FOLLOWUP_PROMPT = ChatPromptTemplate.from_template(
    """Bạn là trợ lý EPR. Dựa trên câu hỏi và câu trả lời vừa rồi, hãy đề xuất 3 câu hỏi gợi ý (follow-up) để người dùng có thể hỏi tiếp.

QUY TẮC:
1. Mỗi câu hỏi phải ngắn gọn, cụ thể, liên quan trực tiếp đến chủ đề vừa trao đổi
2. Không lặp lại câu hỏi đã hỏi
3. Trả lời theo đúng định dạng JSON: ["câu hỏi 1", "câu hỏi 2", "câu hỏi 3"]
4. Không thêm bất kỳ text nào khác ngoài JSON array

CÂU HỎI GỐC: {question}
CÂU TRẢ LỜI: {answer}

Đề xuất follow-up (JSON array):"""
)


async def generate_follow_ups(question: str, answer: str) -> list[str]:
    """Generate 3 suggested follow-up questions based on the Q&A context."""
    try:
        chain = _FOLLOWUP_PROMPT | get_llm_smart() | StrOutputParser()
        result = chain.invoke({"question": question, "answer": answer[:1000]})

        # Parse JSON array from LLM response
        # Strip any markdown code blocks
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("\n", 1)[0]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()

        followups = _json_module.loads(cleaned)
        if isinstance(followups, list) and len(followups) >= 2:
            return followups[:3]
    except Exception:
        logger.debug("Follow-up suggestion generation failed", exc_info=True)

    # Fallback: return empty (no suggestions)
    return []


# ---------------------------------------------------------------------------
# Legal RAG generation (non-streaming, for non-realtime paths)
# ---------------------------------------------------------------------------

_LEGAL_GEN_SYSTEM = """Bạn là trợ lý AI chuyên về pháp luật EPR (Trách nhiệm mở rộng của nhà sản xuất) tại Việt Nam.

NHIỆM VỤ:
1. Trả lời dựa HOÀN TOÀN trên văn bản pháp luật được cung cấp
2. Trích dẫn cụ thể số Điều, Chương, Mục inline khi trả lời (ví dụ: "Theo Điều 77 [1], quy định rằng …")
3. Giải thích rõ ràng, dễ hiểu bằng tiếng Việt
4. Nếu thông tin không có trong tài liệu → nói rõ điều đó
5. Sử dụng định dạng trích dẫn [1], [2], [3] để tham chiếu đến tài liệu nguồn

XỬ LÝ CÂU HỎI MÙ MỜ (follow-up không rõ ràng):
- Nếu người dùng hỏi kiểu "còn luật nào nữa không", "còn gì khác không" → Hỏi lại họ muốn tìm hiểu cụ thể về chủ đề nào, đồng thời gợi ý các chủ đề có sẵn
- KHÔNG liệt kê tràn lan tất cả văn bản

QUY TẮC TRÍCH DẪN:
- Khi đề cập nội dung từ tài liệu [n], dùng dạng rõ ràng, ví dụ: "Theo Điều X [1]" hoặc "Khoản Y Điều Z [2] quy định …"
- Luôn trích dẫn nguồn cụ thể cho mỗi thông tin quan trọng
- Kết thúc câu trả lời bằng phần "📚 Nguồn tham khảo:" (mỗi nguồn một dòng riêng)
- KHÔNG dùng "Tài liệu 1", "Tài liệu 2" — CHỈ dùng số Điều/Chương/Mục với trích dẫn [1], [2]
- Nếu câu hỏi "Điều X có nói về Y không?" mà tài liệu có Điều X nhưng không đề cập Y
  → Trả lời: "KHÔNG, Điều X không đề cập Y. Điều X quy định về …"

QUY TẮC BẮT BUỘC CHO MỤC "📚 Nguồn tham khảo:" (để người đọc biết chính xác văn bản nào):
- Với mỗi chỉ số [n] đã dùng trong câu trả lời, ghi MỘT dòng đầy đủ, KHÔNG được cắt ngắn bằng "...", "…", hay "v.v."
- Mỗi dòng phải lấy nguyên văn (copy đúng) từ khối tài liệu tương ứng trong phần TÀI LIỆU:
  - Dòng "Tên Điều:" (toàn bộ, không rút gọn)
  - Kèm "Tên Chương:" / "Tên Mục:" nếu giá trị khác "N/A" hoặc rỗng
- Nếu trong khối có thể suy ra tên văn bản (ví dụ Nghị định 08/2022/NĐ-CP, Luật Bảo vệ Môi trường 2020) thì ghi đủ tên đó trên cùng dòng; không được viết "Nghị định số..." hay để ngỏ
- Không được bỏ sót nguồn [n] đã trích trong phần trả lời chính

TÀI LIỆU:
{context}

CÂU HỎI: {question}"""

_legal_gen_prompt = ChatPromptTemplate.from_template(_LEGAL_GEN_SYSTEM)


def generate_legal(question: str, docs: list[Document]) -> str:
    """Synchronous legal RAG generation (used as fallback)."""
    if not docs:
        return "Xin lỗi, tôi không tìm thấy thông tin liên quan trong cơ sở dữ liệu."
    context = format_docs(docs)
    chain = _legal_gen_prompt | get_llm_smart() | StrOutputParser()
    return chain.invoke({"context": context, "question": question})


# ---------------------------------------------------------------------------
# Chitchat
# ---------------------------------------------------------------------------

_CHITCHAT_SYSTEM = """Bạn là **Trợ lý Pháp luật Việt Nam** — hệ thống tư vấn và tra cứu pháp luật thông minh, toàn diện.

PHẠM VI NĂNG LỰC & CHỦ ĐỀ CHUYÊN MÔN:
Bạn hỗ trợ tra cứu, đối chiếu căn cứ và hướng dẫn thủ tục trên toàn bộ hệ thống Pháp luật Việt Nam:
- 🏡 **Đất đai & Bất động sản**: Cấp sổ đỏ/sổ hồng, đất khai hoang, tranh chấp, chuyển nhượng (Luật Đất đai 2024).
- 💼 **Lao động & Việc làm**: Hợp đồng lao động, thử việc, tiền lương, kỷ luật, chế độ BHXH/BHYT (Bộ luật Lao động 2019, Luật BHXH).
- ⚖️ **Dân sự & Hợp đồng**: Đặt cọc thuê nhà/mua bán, bồi thường, hợp đồng dân sự, thừa kế (Bộ luật Dân sự 2015).
- 🏢 **Doanh nghiệp & Thương mại**: Thành lập công ty, hộ kinh doanh, cổ phần, phạt hợp đồng (Luật Doanh nghiệp, Luật Thương mại).
- 💰 **Thuế & Tài chính**: Thuế TNCN, giảm trừ gia cảnh, thuế TNDN, thuế GTGT (Luật Quản lý thuế, Luật Thuế TNCN).
- 🌿 **Môi trường & Tuân thủ EPR**: Trách nhiệm tái chế bao bì/sản phẩm, đóng góp Quỹ BVMT, Nghị định 08/2022/NĐ-CP, Luật BVMT 2020.
- 🚗 **Giao thông, Hành chính, PCCC, An toàn thực phẩm**: Quy chuẩn VSATP, phòng cháy chữa cháy, khiếu nại quyết định hành chính.

QUY TẮC PHẢN HỒI:
1. Khi người dùng hỏi "bạn là ai / bạn có thể làm gì / bạn hỗ trợ những gì" → giới thiệu rõ bản thân là **Trợ lý Pháp luật Việt Nam**, tóm tắt các lĩnh vực chính bạn hỗ trợ và gợi ý 2-3 câu hỏi mẫu thực tế.
2. Với câu hỏi chào hỏi / cảm ơn / tạm biệt → phản hồi thân thiện, lịch sự và sẵn sàng hỗ trợ giải đáp bất kỳ vướng mắc pháp luật nào.
3. Với câu hỏi định hướng chung (ví dụ: "cái gì cần quan tâm nhất", "tôi nên bắt đầu từ đâu", "cần lưu ý gì", "hướng dẫn tôi") → Giải thích rằng vấn đề cần quan tâm hàng đầu tùy thuộc vào tư cách người hỏi (Cá nhân, Người lao động, Hộ kinh doanh hay Doanh nghiệp). Nêu ngắn gọn 2-3 điểm mấu chốt (ví dụ: Rà soát điều khoản hợp đồng & đặt cọc, Tuân thủ nghĩa vụ thuế & bảo hiểm lao động, hoặc Bảo đảm pháp lý tài sản/đất đai), sau đó chủ động mời người dùng chia sẻ cụ thể ngành nghề hoặc tình huống đang gặp phải.
4. Luôn đọc kỹ ngữ cảnh lịch sử hội thoại trước khi phản hồi.
5. Giọng điệu khách quan, chuẩn mực, dễ hiểu và tôn trọng người dân/doanh nghiệp.

Lịch sử hội thoại:
{chat_history}"""

_chitchat_prompt = ChatPromptTemplate.from_messages([
    ("system", _CHITCHAT_SYSTEM),
    ("human", "{question}"),
])


def chitchat_response(question: str, chat_history: str) -> str:
    """Non-streaming chitchat (legacy, kept for backward compatibility)."""
    chain = _chitchat_prompt | get_llm_fast() | StrOutputParser()
    return chain.invoke({
        "question": question,
        "chat_history": chat_history or "(không có hội thoại trước)",
    })


async def stream_chitchat_response(question: str, chat_history: str) -> AsyncIterator[str]:
    """
    Streaming chitchat response - token by token.
    
    CRITICAL PERF FIX: Instead of waiting 5s for full response then yielding all at once,
    this streams tokens as they arrive, giving user immediate feedback after ~2s.
    """
    chain = _chitchat_prompt | get_llm_stream()
    async for chunk in chain.astream({
        "question": question,
        "chat_history": chat_history or "(không có hội thoại trước)",
    }):
        content = _chunk_text(getattr(chunk, "content", ""))
        if content:
            yield content


# ---------------------------------------------------------------------------
# Web search fallback (Tavily)
# ---------------------------------------------------------------------------

# Keywords indicating the question is at least tangentially related to EPR.
# If none match, we skip Tavily entirely and return a polite domain decline.
# This set is intentionally broad — single-character false positives are
# acceptable (fail toward Tavily) but clearly off-domain queries must be caught.
_EPR_KEYWORDS = {
    "epr", "tái chế", "bao bì", "nghị định", "nhà sản xuất", "nhập khẩu",
    "môi trường", "chất thải", "ắc quy", "pin", "dầu nhớt", "săm lốp",
    "phương tiện", "quỹ", "tái ché", "điều ", "luật", "quy định", "trách nhiệm",
    "tái sử dụng", "thu hồi", "xử lý", "bvmt", "recycl", "producer",
    "tham vấn", "đánh giá tác động", "đtm", "giấy phép", "quan trắc",
    "khí thải", "nước thải", "chất thải rắn", "nguy hại",
}


def _is_epr_related(question: str) -> bool:
    """Fast keyword check — True if query is plausibly EPR-domain."""
    q = question.lower()
    return any(kw in q for kw in _EPR_KEYWORDS)


def _clean_tavily_snippet(content: str, max_chars: int = 500) -> str:
    """
    Clean a raw Tavily snippet by removing common noise patterns.

    Tavily returns raw webpage content that often includes navigation menus,
    tables, ads, headers, footers, and other junk. This function strips the
    most problematic patterns to leave readable content.
    """
    if not content:
        return ""

    # Remove table rows (Tavily often returns markdown tables from legal sites)
    # Strip lines that are mostly table formatting (pipes and dashes)
    lines = content.split('\n')
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        # Skip lines that are mostly table/pipe formatting
        if stripped.count('|') > 3 and len(stripped) > 50:
            continue
        # Skip nav/menu items (short links-like patterns)
        if stripped.startswith('[') and '](' in stripped and len(stripped) < 80:
            continue
        # Skip lines that are just dots or dashes
        if re.match(r'^[\.\-\*\=\#]{3,}$', stripped):
            continue
        # Skip lines with excessive repetition of same char
        if len(stripped) > 20 and any(c * 15 in stripped for c in '|='):
            continue
        cleaned_lines.append(stripped)

    cleaned = '\n'.join(line for line in cleaned_lines if line).strip()

    # Truncate to max_chars
    if len(cleaned) > max_chars:
        # Truncate at sentence boundary
        truncated = cleaned[:max_chars]
        last_period = truncated.rfind('.')
        if last_period > max_chars * 0.5:
            truncated = truncated[:last_period + 1]
        return truncated + '...'

    return cleaned


def _synthesize_web_results(question: str, results: list) -> str | None:
    """
    Use LLM to synthesize a clean, concise answer from Tavily search results.

    Instead of dumping raw snippets, this sends the search results to the LLM
    and asks it to generate a clean answer.
    """
    # Build a compact context from cleaned snippets
    context_parts = []
    for i, r in enumerate(results[:3], 1):  # Use top 3 results
        title = r.get("title", "")
        url = r.get("url", "")
        content = _clean_tavily_snippet(r.get("content", "") or r.get("answer", ""), max_chars=600)
        if content:
            context_parts.append(f"[{i}] {title}\n{content}\nNguồn: {url}")

    if not context_parts:
        return None

    context = "\n\n---\n\n".join(context_parts)

    synthesis_prompt = ChatPromptTemplate.from_template(
        """Bạn là trợ lý pháp lý EPR. Dựa trên các kết quả tìm kiếm dưới đây, hãy trả lời câu hỏi của người dùng một cách ngắn gọn, rõ ràng.

QUY TẮC:
1. Chỉ trả lời dựa trên thông tin có trong các kết quả tìm kiếm
2. Trả lời ngắn gọn, tập trung vào câu hỏi (tối đa 3-4 câu)
3. Trích dẫn nguồn bằng URL ngắn gọn ở cuối (dạng: Nguồn: ten-mien)
4. KHÔNG sao chép nguyên văn bảng, menu, hoặc nội dung rác từ web
5. Nếu thông tin không đủ → nói rõ, đừng bịa đáp án
6. Luôn kèm cảnh báo: "⚠️ Vui lòng đối chiếu với văn bản pháp luật chính thức."

TÀI LIỆU TÌM KIẾM:
{context}

CÂU HỎI: {question}

Trả lời:"""
    )

    try:
        chain = synthesis_prompt | get_llm_smart() | StrOutputParser()
        return chain.invoke({"context": context, "question": question})
    except Exception:
        logger.warning("Web result synthesis failed", exc_info=True)
        return None


def web_fallback(question: str) -> str:
    """EPR-scoped web search via Tavily.

    Called only after FAQ + legal retrieval both miss. Before hitting Tavily,
    a fast keyword check gates off genuinely off-domain queries (stock prices,
    sports, cooking, etc.) so we never burn Tavily API budget on them.

    Uses LLM to synthesize clean answers from raw search results instead of
    dumping snippets directly.
    """
    # Gate 1 — keyword guard: decline immediately if no EPR signal in query
    if not _is_epr_related(question):
        return (
            "Câu hỏi này nằm ngoài phạm vi chuyên môn của tôi.\n\n"
            "Tôi chỉ hỗ trợ các câu hỏi về **Luật EPR** và **Nghị định 08/2022/NĐ-CP** "
            "về trách nhiệm tái chế sản phẩm, bao bì tại Việt Nam.\n\n"
            "Bạn có thể hỏi tôi về:\n"
            "- Tỷ lệ tái chế bắt buộc theo loại sản phẩm\n"
            "- Đối tượng phải thực hiện EPR (nhà sản xuất, nhập khẩu)\n"
            "- Quy trình đăng ký kế hoạch tái chế\n"
            "- Mức đóng góp tài chính vào Quỹ Bảo vệ Môi trường\n"
            "- Các điều khoản trong Nghị định 08/2022/NĐ-CP"
        )

    tavily_key = os.getenv("TAVILY_API_KEY", "")
    if not tavily_key or tavily_key.startswith("your-"):
        return (
            "Thông tin bạn hỏi chưa có trong cơ sở dữ liệu EPR nội bộ.\n\n"
            "Vui lòng thử diễn đạt lại câu hỏi theo hướng EPR/tái chế/Nghị định 08, "
            "hoặc liên hệ chuyên gia pháp lý để được hỗ trợ."
        )
    try:
        try:
            # Preferred path (new package, avoids deprecation warning).
            from langchain_tavily import TavilySearch  # type: ignore

            def _search(query: str):
                tool = TavilySearch(
                    max_results=3,
                    include_answer=True,
                    search_depth="advanced",
                )
                return tool.invoke({"query": query})

        except Exception:  # noqa: BLE001 - this boundary supports either Tavily integration at runtime
            # Backward-compatible fallback for older environments.
            from langchain_community.tools.tavily_search import TavilySearchResults

            def _search(query: str):
                # Keep compatibility with older stacks while muting the known
                # deprecation warning for this legacy class path.
                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore",
                        message=r".*TavilySearchResults.*deprecated.*",
                    )
                    tool = TavilySearchResults(  # type: ignore[call-arg]
                        k=3,
                        include_answer=True,
                        search_depth="advanced",
                    )
                return tool.invoke({"query": query})

        # Always scope the Tavily query to EPR + Vietnam legal context.
        epr_scoped_query = f"EPR tái chế pháp luật Việt Nam {question}"
        results = _search(epr_scoped_query)

        if not results:
            return (
                f"Không tìm thấy thông tin liên quan đến EPR cho câu hỏi: \"{question}\".\n\n"
                "Câu hỏi này có thể nằm ngoài phạm vi Nghị định 08/2022/NĐ-CP. "
                "Vui lòng thử hỏi về trách nhiệm tái chế, tỷ lệ tái chế, hoặc các điều khoản EPR cụ thể."
            )

        # Try LLM synthesis first
        synthesized = _synthesize_web_results(question, results)
        if synthesized:
            return synthesized

        # Fallback: show cleaned snippets if synthesis fails
        lines = [
            ("Không tìm thấy trong cơ sở dữ liệu nội bộ. "
            "Dưới đây là thông tin từ web về EPR:\n")
        ]
        for i, r in enumerate(results, 1):
            title = r.get("title", "Không có tiêu đề")
            url = r.get("url", "")
            content = _clean_tavily_snippet(r.get("content", "") or r.get("answer", ""), max_chars=400)

            if content:
                lines.append(f"\n### {i}. {title}")
                lines.append(f"**🔗 Nguồn:** [{url}]({url})")
                lines.append(f"\n{content}\n")

        lines.append("\n---")
        lines.append("\n⚠️ Các nguồn trên từ Internet — vui lòng đối chiếu với văn bản pháp luật chính thức.")
        return "\n".join(lines)
    except Exception:
        logger.warning("Explicit web research failed", exc_info=True)
        return "Không thể thực hiện tìm kiếm lúc này. Vui lòng thử lại sau hoặc đối chiếu trực tiếp với nguồn pháp luật chính thức."


# ---------------------------------------------------------------------------
# Streaming generators
# ---------------------------------------------------------------------------

_FAQ_STREAM_SYSTEM = """Bạn là EPR Legal Assistant — trợ lý pháp lý chuyên về Nghị định 08/2022/NĐ-CP và Luật EPR tại Việt Nam.

Nhiệm vụ:
1. Dựa vào câu hỏi FAQ và câu trả lời mẫu bên dưới để trả lời câu hỏi người dùng một cách tự nhiên
2. Giữ nguyên 100% thông tin chính xác từ FAQ (số liệu, tỷ lệ, tên điều luật); chỉ điều chỉnh cách diễn đạt
3. Trả lời bằng tiếng Việt, rõ ràng, có trích dẫn điều luật nếu FAQ có đề cập
4. KHÔNG được từ chối trả lời nếu đã có tài liệu FAQ phù hợp — hãy dùng thông tin đó

Câu hỏi FAQ tương tự: {faq_question}
Câu trả lời FAQ: {faq_answer}
Câu hỏi của người dùng: {user_question}"""

_faq_stream_prompt = ChatPromptTemplate.from_template(_FAQ_STREAM_SYSTEM)


async def stream_faq_answer(user_query: str, faq_doc: Document) -> AsyncIterator[str]:
    """Stream an FAQ-based answer token-by-token."""
    chain = _faq_stream_prompt | get_llm_stream()
    async for chunk in chain.astream({
        "faq_question": faq_doc.metadata.get("Câu_hỏi", ""),
        "faq_answer": faq_doc.page_content,
        "user_question": user_query,
    }):
        content = _chunk_text(getattr(chunk, "content", ""))
        if content:
            yield content


_LEGAL_STREAM_SYSTEM = """Bạn là trợ lý AI chuyên về pháp luật EPR tại Việt Nam.

Dựa trên các văn bản pháp luật dưới đây, hãy trả lời câu hỏi một cách chi tiết:
- Trích dẫn số Điều/Chương/Mục cụ thể inline trong câu trả lời (ví dụ: "Theo Điều 77 [1], quy định rằng …")
- Giải thích rõ ràng các điều khoản liên quan
- Nêu rõ các nghĩa vụ, quyền lợi và chế tài xử phạt (nếu có)
- Sử dụng định dạng trích dẫn [1], [2], [3] để tham chiếu đến tài liệu nguồn

QUY TẮC TRÍCH DẪN:
- Khi đề cập nội dung từ tài liệu [n], dùng dạng rõ ràng, ví dụ: "Theo Điều X [1]" hoặc "Khoản Y Điều Z [2] quy định …"
- Luôn trích dẫn nguồn cụ thể cho mỗi thông tin quan trọng
- Kết thúc câu trả lời bằng phần "📚 Nguồn tham khảo:" (mỗi nguồn một dòng riêng)

QUY TẮC BẮT BUỘC CHO MỤC "📚 Nguồn tham khảo:" (để người đọc biết chính xác văn bản nào):
- Với mỗi chỉ số [n] đã dùng, ghi MỘT dòng đầy đủ; TUYỆT ĐỐI KHÔNG dùng "...", "…", hay "v.v." để cắt tên điều hay tên văn bản
- Mỗi dòng: copy nguyên văn "Tên Điều:" từ khối tài liệu [n]; thêm "Tên Chương:" / "Tên Mục:" nếu có và khác N/A
- Ghi đủ tên văn bản pháp luật khi suy ra được từ ngữ cảnh (không viết dở như "Nghị định số...")
- Không bỏ sót nguồn [n] đã trích trong phần trả lời chính

Văn bản pháp luật:
{context}

Câu hỏi: {question}

Trả lời:"""

_legal_stream_prompt = ChatPromptTemplate.from_template(_LEGAL_STREAM_SYSTEM)


async def stream_legal_answer(question: str, docs: list[Document]) -> AsyncIterator[str]:
    """Stream a legal RAG answer token-by-token."""
    context = format_docs(docs)
    chain = _legal_stream_prompt | get_llm_stream()
    async for chunk in chain.astream({"context": context, "question": question}):
        content = _chunk_text(getattr(chunk, "content", ""))
        if content:
            yield content
