"""
LLM-as-judge evaluators for Vietnam Legal Agent quality assessment.

Three dimensions (each scored 0–5 by gpt-4o-mini):
  - Faithfulness  : every claim in the answer is grounded in the retrieved documents
  - Relevance     : the answer directly addresses the user's question
  - Completeness  : the answer covers all important aspects of the question

Usage:
    from tests.eval.evaluators import eval_faithfulness, eval_relevance, eval_completeness

    score = eval_faithfulness(question, answer, documents)
    print(score.score, score.reasoning)
"""

# An evaluator must convert any third-party model failure into an EvalScore.
# ruff: noqa: BLE001

from __future__ import annotations

import logging

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── Output schema ─────────────────────────────────────────────────────────────

class EvalScore(BaseModel):
    score: int = Field(ge=0, le=5, description="Quality score from 0 (worst) to 5 (best)")
    reasoning: str = Field(description="One-sentence justification for the score")


# ── Shared helper ─────────────────────────────────────────────────────────────

def _judge_llm():
    """gpt-4o-mini with structured output — used for all judge calls."""
    from backend.core.llm_instances import get_llm_smart
    return get_llm_smart().with_structured_output(EvalScore)


# ── Faithfulness evaluator ────────────────────────────────────────────────────

_FAITHFULNESS_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        """Bạn là chuyên gia kiểm tra độ trung thực của câu trả lời pháp luật.

Nhiệm vụ: Đánh giá xem mỗi thông tin trong câu trả lời có được hỗ trợ bởi TÀI LIỆU được cung cấp không.
Chỉ dùng tài liệu đã cho — KHÔNG dùng kiến thức ngoài.

Thang điểm FAITHFULNESS (0–5):
  5 — Mọi thông tin đều có căn cứ rõ ràng trong tài liệu
  4 — Hầu hết thông tin có căn cứ; có 1–2 chi tiết nhỏ ngoài tài liệu nhưng không sai
  3 — Khoảng nửa thông tin có căn cứ; nửa còn lại không xác minh được
  2 — Phần lớn thông tin không có trong tài liệu hoặc mâu thuẫn
  1 — Câu trả lời chủ yếu là thông tin suy diễn/bịa đặt
  0 — Hoàn toàn không liên quan đến tài liệu""",
    ),
    (
        "human",
        """Câu hỏi: {question}

Tài liệu tham khảo:
{documents}

Câu trả lời của legal agent:
{answer}

Hãy chấm điểm FAITHFULNESS.""",
    ),
])


def eval_faithfulness(
    question: str,
    answer: str,
    documents: list[dict],
) -> EvalScore:
    """Score how faithfully the answer is grounded in the retrieved documents."""
    if not documents:
        return EvalScore(score=0, reasoning="Không có tài liệu nào được truy xuất để kiểm tra.")

    doc_text = "\n\n---\n\n".join(
        f"[{i+1}] {d.get('page_content', '')[:600]}"
        for i, d in enumerate(documents[:5])
    )
    try:
        chain = _FAITHFULNESS_PROMPT | _judge_llm()
        return chain.invoke({"question": question, "documents": doc_text, "answer": answer})
    except Exception as exc:
        logger.warning("faithfulness eval failed: %s", exc)
        return EvalScore(score=0, reasoning=f"Eval error: {exc}")


# ── Relevance evaluator ───────────────────────────────────────────────────────

_RELEVANCE_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        """Bạn là chuyên gia đánh giá chất lượng câu trả lời của legal agent.

Nhiệm vụ: Đánh giá mức độ LIÊN QUAN — câu trả lời có đúng trọng tâm câu hỏi không?

Thang điểm RELEVANCE (0–5):
  5 — Câu trả lời hoàn toàn đúng trọng tâm, giải đáp chính xác điều được hỏi
  4 — Câu trả lời phần lớn đúng trọng tâm, chỉ có chi tiết phụ lệch chủ đề
  3 — Đề cập đến chủ đề nhưng không trả lời đúng câu hỏi
  2 — Chỉ liên quan một phần nhỏ, phần lớn lạc đề
  1 — Gần như không liên quan
  0 — Hoàn toàn không liên quan hoặc là lỗi""",
    ),
    (
        "human",
        """Câu hỏi: {question}

Câu trả lời:
{answer}

Hãy chấm điểm RELEVANCE.""",
    ),
])


def eval_relevance(question: str, answer: str) -> EvalScore:
    """Score how directly the answer addresses the question."""
    try:
        chain = _RELEVANCE_PROMPT | _judge_llm()
        return chain.invoke({"question": question, "answer": answer})
    except Exception as exc:
        logger.warning("relevance eval failed: %s", exc)
        return EvalScore(score=0, reasoning=f"Eval error: {exc}")


# ── Completeness evaluator ────────────────────────────────────────────────────

_COMPLETENESS_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        """Bạn là chuyên gia đánh giá tính đầy đủ của câu trả lời pháp luật.

Nhiệm vụ: Đánh giá mức độ ĐẦY ĐỦ — câu trả lời có bao phủ các khía cạnh quan trọng không?

Thang điểm COMPLETENESS (0–5):
  5 — Bao phủ đầy đủ tất cả khía cạnh quan trọng của câu hỏi, có trích dẫn pháp lý
  4 — Bao phủ hầu hết các khía cạnh, có thể thiếu 1 chi tiết nhỏ
  3 — Bao phủ khoảng nửa các khía cạnh quan trọng
  2 — Chỉ đề cập một vài điểm sơ lược, thiếu nhiều nội dung trọng tâm
  1 — Câu trả lời rất sơ lược, gần như không có thông tin có ích
  0 — Không cung cấp thông tin có ích""",
    ),
    (
        "human",
        """Câu hỏi: {question}

Câu trả lời:
{answer}

Hãy chấm điểm COMPLETENESS.""",
    ),
])


def eval_completeness(question: str, answer: str) -> EvalScore:
    """Score how completely the answer covers the important aspects of the question."""
    try:
        chain = _COMPLETENESS_PROMPT | _judge_llm()
        return chain.invoke({"question": question, "answer": answer})
    except Exception as exc:
        logger.warning("completeness eval failed: %s", exc)
        return EvalScore(score=0, reasoning=f"Eval error: {exc}")
