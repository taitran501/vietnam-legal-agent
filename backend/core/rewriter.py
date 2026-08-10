"""
Question rewriter that resolves pronouns / co-references using chat history.
Uses gpt-4o-mini with an extensive few-shot prompt (ported from the original).
"""

from __future__ import annotations

from functools import lru_cache

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from backend.core.llm_instances import get_llm_smart

_SYSTEM = """Bạn là chuyên gia viết lại câu hỏi pháp luật.

**NHIỆM VỤ:**
1. Nếu câu hỏi có ĐẠI TỪ tham chiếu (đó, này, nó) → Thay thế bằng thông tin cụ thể từ lịch sử
2. Nếu câu hỏi ĐÃ RÕ RÀNG (không có đại từ mơ hồ) → GIỮ NGUYÊN
3. Nếu câu hỏi KHÔNG liên quan đến pháp luật → GIỮ NGUYÊN

**CÁC DẠNG THAM CHIẾU CẦN XỬ LÝ:**
- "nó", "đó", "này", "điều đó", "luật đó", "ở trên", "vừa rồi", "điều vừa đề cập" → Thay bằng Điều/Luật/Chương cụ thể
- "các điều ở trên", "những điều đã nói", "các luật ở trên" → Liệt kê các Điều cụ thể từ lịch sử
- "từ các điều trên", "dựa vào các điều đã nói" → Xác định các Điều từ lịch sử

**⚠️ CỰC KỲ QUAN TRỌNG:**
- CHỈ thay thế đại từ, KHÔNG thay đổi số điều cụ thể
- Nếu câu hỏi đã có SỐ ĐIỀU CỤ THỂ (ví dụ: "điều 2", "Điều 77") → GIỮ NGUYÊN HOÀN TOÀN
- TUYỆT ĐỐI KHÔNG thay đổi số điều trong câu hỏi gốc
- KHÔNG thêm từ khóa từ lịch sử vào câu hỏi đã rõ ràng

**QUY TẮC QUAN TRỌNG:**
✅ CHỈ thay thế khi có đại từ mơ hồ
✅ KHÔNG thêm ngữ cảnh vào câu hỏi đã rõ ràng
✅ KHÔNG thêm "theo Điều X" vào câu hỏi mới về chủ đề khác
✅ ĐỌC KỸ lịch sử để tìm Điều/Chương/Luật được nhắc đến
✅ CHỈ trả về câu hỏi ngắn gọn (10-20 từ)
✅ LUÔN giữ dạng câu hỏi với dấu "?"

❌ TUYỆT ĐỐI KHÔNG trả lời câu hỏi
❌ TUYỆT ĐỐI KHÔNG giải thích nội dung luật
❌ TUYỆT ĐỐI KHÔNG thêm ngữ cảnh khi câu hỏi đã rõ ràng"""

_rewrite_prompt = ChatPromptTemplate.from_messages([
    ("system", _SYSTEM),
    # Few-shot: pronoun case → rewrite
    ("human", "Lịch sử: User: Cho tôi biết về điều 1? Assistant: Theo Điều 1...\nUser: Cho tôi biết về điều 3? Assistant: Theo Điều 3...\n\nCâu hỏi: Từ các điều ở trên hãy cho tôi biết áp dụng được gì không?"),
    ("assistant", "Điều 1 và Điều 3 có thể áp dụng được gì?"),
    ("human", "Lịch sử: User: Cho tôi hỏi về điều luật số 7? Assistant: Theo Điều 7...\n\nCâu hỏi: Điều luật đó có nói về không khí hay không?"),
    ("assistant", "Điều 7 có nói về không khí không?"),
    # Few-shot: already-clear question → keep original
    ("human", "Lịch sử: User: Cho tôi hỏi về Điều 7? Assistant: Theo Điều 7... nói về quản lý không khí\n\nCâu hỏi: Ai chịu trách nhiệm tái chế?"),
    ("assistant", "Ai chịu trách nhiệm tái chế?"),
    ("human", "Lịch sử: User: Điều 77 là gì? Assistant: Điều 77 về tái chế...\n\nCâu hỏi: Quy định về bao bì là gì?"),
    ("assistant", "Quy định về bao bì là gì?"),
    # Few-shot: specific article numbers → never change them
    ("human", "Lịch sử: User: Điều 5 là gì? Assistant: Điều 5...\nUser: Điều 6? Assistant: Điều 6...\n\nCâu hỏi: Cho tôi hỏi chi tiết về điều 2 và điều 3?"),
    ("assistant", "Cho tôi hỏi chi tiết về điều 2 và điều 3?"),
    # Few-shot: empty history
    ("human", "Lịch sử: (trống)\n\nCâu hỏi: Cho tôi hỏi về điều luật số 1?"),
    ("assistant", "Điều 1 quy định gì?"),
    # Actual query
    ("human", "Lịch sử: {chat_history}\n\nCâu hỏi: {question}\n\nCâu hỏi viết lại (CHỈ câu hỏi ngắn, hoặc giữ nguyên nếu đã rõ):"),
])


@lru_cache(maxsize=1)
def _get_rewriter():
    return _rewrite_prompt | get_llm_smart() | StrOutputParser()


def rewrite_question(question: str, chat_history: str) -> str:
    """Return the rewritten question (or original if already clear)."""
    if not chat_history or chat_history.strip() in ("", "(trống)"):
        return question
    try:
        return _get_rewriter().invoke({
            "question": question,
            "chat_history": chat_history,
        })
    except Exception:  # noqa: BLE001 - rewrite failure must preserve the original user question
        return question
