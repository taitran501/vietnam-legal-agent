"""RAGAS Evaluation Framework tailored for Vietnamese Legal Assistance.

Computes 5 quantitative dimensions:
1. Faithfulness (Độ trung thực - 0.0 to 1.0):
   Ratio of claims in the generated answer that are directly supported by the retrieved statutory evidence.
2. Answer Relevance (Độ trúng đích - 0.0 to 1.0):
   Semantic alignment between the user's inquiry and the generated answer.
3. Context Precision (Độ chính xác của ngữ cảnh - 0.0 to 1.0):
   Proportion of retrieved legal provisions that are genuinely useful/relevant to answering the query.
4. Context Recall (Độ bao phủ của ngữ cảnh - 0.0 to 1.0):
   Extent to which the retrieved documents contain the required ground-truth statutory anchors (Điều, Khoản, Luật).
5. Statutory Anchor Accuracy (Độ chuẩn xác căn cứ luật - 0.0 to 1.0):
   Accuracy of explicit statutory references cited in the answer against the
   declared benchmark anchors.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, cast

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class StatementClaim(BaseModel):
    """An individual factual claim extracted from an answer."""

    statement: str = Field(description="Mệnh đề khẳng định độc lập trong câu trả lời")
    is_supported: bool = Field(description="Có căn cứ chứng minh trực tiếp trong tài liệu hay không")
    supporting_quote: str = Field(default="", description="Đoạn trích trong tài liệu chứng minh mệnh đề")
    contradiction_reason: str | None = Field(default=None, description="Lý do nếu không có căn cứ hoặc mâu thuẫn")


class FaithfulnessEvaluation(BaseModel):
    """Detailed Faithfulness assessment output."""

    statements: list[StatementClaim] = Field(default_factory=list, description="Danh sách các mệnh đề phân tích")
    faithfulness_score: float = Field(ge=0.0, le=1.0, description="Tỷ lệ mệnh đề có căn cứ (0.0 - 1.0)")
    summary: str = Field(description="Tóm tắt nhận định về độ trung thực")


class RelevanceEvaluation(BaseModel):
    """Answer Relevance assessment output."""

    relevance_score: float = Field(ge=0.0, le=1.0, description="Điểm độ liên quan (0.0 - 1.0)")
    is_fully_answering: bool = Field(description="Câu trả lời có giải quyết trọn vẹn câu hỏi không")
    off_topic_parts: list[str] = Field(default_factory=list, description="Các phần thông tin thừa/lạc đề nếu có")
    reasoning: str = Field(description="Giải thích chi tiết điểm số")


class ContextPrecisionEvaluation(BaseModel):
    """Context Precision assessment output."""

    useful_doc_indices: list[int] = Field(default_factory=list, description="Chỉ số các tài liệu thực sự hữu ích")
    precision_score: float = Field(ge=0.0, le=1.0, description="Tỷ lệ tài liệu hữu ích trên tổng số (0.0 - 1.0)")
    reasoning: str = Field(description="Đánh giá chất lượng của bộ tài liệu truy xuất")


class RagasSampleResult(BaseModel):
    """Complete RAGAS metric bundle for a single evaluation turn."""

    sample_id: str
    query: str
    faithfulness: float = Field(ge=0.0, le=1.0)
    answer_relevance: float = Field(ge=0.0, le=1.0)
    context_precision: float = Field(ge=0.0, le=1.0)
    context_recall: float = Field(ge=0.0, le=1.0)
    anchor_accuracy: float = Field(ge=0.0, le=1.0)
    overall_ragas_score: float = Field(ge=0.0, le=1.0)
    passed_gate: bool
    evaluator_status: str = Field(default="ok", description="ok or evaluation_unavailable")
    details: dict[str, Any] = Field(default_factory=dict)


def compute_context_recall(
    retrieved_docs: list[dict[str, Any]],
    expected_anchors: list[str],
) -> tuple[float, list[str]]:
    """Compute context recall based on presence of expected statutory anchors in retrieved texts."""
    if not expected_anchors:
        return 1.0, []

    combined_text = " ".join(
        f"{d.get('page_content', '')} {json.dumps(d.get('metadata', {}), ensure_ascii=False)}"
        for d in retrieved_docs
    ).lower()

    found_anchors = []
    for anchor in expected_anchors:
        clean_anchor = anchor.lower().strip()
        # Check standard Điều X or anchor text
        if clean_anchor in combined_text:
            found_anchors.append(anchor)
        else:
            # Handle numeric pattern: 'Điều 41' -> 'điều 41' or 'dieu 41'
            digits = re.findall(r"\d+", clean_anchor)
            if digits and any(f"điều {d}" in combined_text or f"dieu_{d}" in combined_text for d in digits):
                found_anchors.append(anchor)

    recall = len(found_anchors) / len(expected_anchors)
    return round(recall, 3), found_anchors


def compute_anchor_accuracy(
    answer: str,
    expected_anchors: list[str],
) -> tuple[float, list[str]]:
    """Compute citation accuracy: how many of the expected statutory anchors are cited in the answer."""
    if not expected_anchors:
        return 1.0, []

    answer_lower = answer.lower()
    cited = []
    for anchor in expected_anchors:
        clean_anchor = anchor.lower().strip()
        if clean_anchor in answer_lower:
            cited.append(anchor)
        else:
            digits = re.findall(r"\d+", clean_anchor)
            if digits and any(f"điều {d}" in answer_lower for d in digits):
                cited.append(anchor)

    accuracy = len(cited) / len(expected_anchors)
    return round(accuracy, 3), cited


_FAITHFULNESS_EXTRACTOR_PROMPT = """Bạn là Chuyên gia Đánh giá RAGAS (Faithfulness Evaluator) cho Hệ thống Trợ lý Pháp luật Việt Nam.
Nhiệm vụ:
1. Chia câu trả lời của trợ lý thành từng mệnh đề khẳng định (statements) độc lập.
2. Với mỗi mệnh đề, kiểm tra xem có căn cứ chứng minh trực tiếp trong phần TÀI LIỆU TRUY XUẤT hay không.
3. Tính tỷ lệ faithfulness_score = (số mệnh đề có căn cứ) / (tổng số mệnh đề).
Chỉ dựa vào TÀI LIỆU được cung cấp, tuyệt đối không dùng kiến thức bên ngoài."""

_RELEVANCE_EVAL_PROMPT = """Bạn là Chuyên gia Đánh giá RAGAS (Answer Relevance Evaluator) cho Hệ thống Trợ lý Pháp luật Việt Nam.
Nhiệm vụ:
1. Đánh giá xem câu trả lời có giải đáp đúng trọng tâm, đầy đủ và trực tiếp câu hỏi của người dùng không.
2. Chấm điểm relevance_score từ 0.0 (hoàn toàn lạc đề/không liên quan) đến 1.0 (trúng đích hoàn hảo, rõ ràng, đúng trọng tâm)."""

_PRECISION_EVAL_PROMPT = """Bạn là Chuyên gia Đánh giá RAGAS (Context Precision Evaluator).
Nhiệm vụ:
1. Xem xét danh sách các tài liệu được truy xuất theo thứ tự (index 0, 1, 2...).
2. Xác định các tài liệu nào thực sự chứa thông tin cần thiết để giải đáp câu hỏi của người dùng.
3. Tính precision_score = (số tài liệu hữu ích) / (tổng số tài liệu được cấp)."""


async def evaluate_ragas_sample(
    query: str,
    answer: str,
    retrieved_docs: list[dict[str, Any]],
    expected_anchors: list[str] | None = None,
    sample_id: str = "sample_001",
    pass_threshold: float = 0.80,
) -> RagasSampleResult:
    """Run comprehensive RAGAS evaluation on a single legal query-answer pair."""
    from epr_agent.infra.llm_instances import get_llm_smart

    expected_anchors = expected_anchors or []

    # 1. Context Recall & Anchor Accuracy (Deterministic)
    context_recall, found_anchors = compute_context_recall(retrieved_docs, expected_anchors)
    anchor_accuracy, cited_anchors = compute_anchor_accuracy(answer, expected_anchors)

    # 2. LLM-as-a-Judge for Faithfulness & Answer Relevance & Context Precision
    doc_text = "\n\n---\n\n".join(
        f"[Tài liệu {i}] (Metadata: {json.dumps(d.get('metadata', {}), ensure_ascii=False)})\n{d.get('page_content', '')[:1000]}"
        for i, d in enumerate(retrieved_docs[:6])
    )

    faithfulness_score = 0.0
    relevance_score = 0.0
    precision_score = 0.0
    evaluator_status = "ok"
    details: dict[str, Any] = {
        "found_anchors": found_anchors,
        "cited_anchors": cited_anchors,
    }

    try:
        judge_llm = get_llm_smart()

        # A. Faithfulness
        faith_chain = judge_llm.with_structured_output(FaithfulnessEvaluation)
        faith_res = cast(FaithfulnessEvaluation, await faith_chain.ainvoke(
            [
                ("system", _FAITHFULNESS_EXTRACTOR_PROMPT),
                (
                    "human",
                    f"Câu hỏi: {query}\n\nTÀI LIỆU TRUY XUẤT:\n{doc_text}\n\nCÂU TRẢ LỜI CẦN ĐÁNH GIÁ:\n{answer}",
                ),
            ]
        ))
        if isinstance(faith_res, FaithfulnessEvaluation):
            faithfulness_score = max(0.0, min(1.0, float(faith_res.faithfulness_score)))
            details["faithfulness_details"] = faith_res.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001 - evaluator health is part of the gate
        logger.warning("RAGAS Faithfulness evaluation error: %s", exc)
        evaluator_status = "evaluation_unavailable"
        details["faithfulness_error"] = str(exc)

    try:
        judge_llm = get_llm_smart()

        # B. Answer Relevance
        rel_chain = judge_llm.with_structured_output(RelevanceEvaluation)
        rel_res = cast(RelevanceEvaluation, await rel_chain.ainvoke(
            [
                ("system", _RELEVANCE_EVAL_PROMPT),
                (
                    "human",
                    f"CÂU HỎI:\n{query}\n\nCÂU TRẢ LỜI:\n{answer}",
                ),
            ]
        ))
        if isinstance(rel_res, RelevanceEvaluation):
            relevance_score = max(0.0, min(1.0, float(rel_res.relevance_score)))
            details["relevance_details"] = rel_res.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001 - evaluator health is part of the gate
        logger.warning("RAGAS Relevance evaluation error: %s", exc)
        evaluator_status = "evaluation_unavailable"
        details["relevance_error"] = str(exc)

    try:
        judge_llm = get_llm_smart()

        # C. Context Precision
        prec_chain = judge_llm.with_structured_output(ContextPrecisionEvaluation)
        prec_res = cast(ContextPrecisionEvaluation, await prec_chain.ainvoke(
            [
                ("system", _PRECISION_EVAL_PROMPT),
                (
                    "human",
                    f"CÂU HỎI:\n{query}\n\nCÁC TÀI LIỆU ĐƯỢC CẤP:\n{doc_text}",
                ),
            ]
        ))
        if isinstance(prec_res, ContextPrecisionEvaluation):
            precision_score = max(0.0, min(1.0, float(prec_res.precision_score)))
            details["precision_details"] = prec_res.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001 - evaluator health is part of the gate
        logger.warning("RAGAS Precision evaluation error: %s", exc)
        evaluator_status = "evaluation_unavailable"
        details["precision_error"] = str(exc)

    # Harmonic mean or weighted composite RAGAS score
    weights = [0.30, 0.25, 0.20, 0.15, 0.10]
    scores = [faithfulness_score, relevance_score, context_recall, precision_score, anchor_accuracy]
    # Do not expose a partially-computed composite as if it were a valid
    # quality score. Deterministic anchor metrics remain in ``details`` while
    # an unavailable judge makes the promotion score explicitly unusable.
    overall = sum(w * s for w, s in zip(weights, scores)) if evaluator_status == "ok" else 0.0

    passed = (
        evaluator_status == "ok"
        and overall >= pass_threshold
        and faithfulness_score >= 0.75
    )

    return RagasSampleResult(
        sample_id=sample_id,
        query=query,
        faithfulness=round(faithfulness_score, 3),
        answer_relevance=round(relevance_score, 3),
        context_precision=round(precision_score, 3),
        context_recall=round(context_recall, 3),
        anchor_accuracy=round(anchor_accuracy, 3),
        overall_ragas_score=round(overall, 3),
        passed_gate=passed,
        evaluator_status=evaluator_status,
        details=details,
    )
