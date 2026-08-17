"""Tool Registry for Autonomous EPR Legal Agent.

Defines the 7 tools available for the LLM to call during its cognitive loop.
Each tool wraps existing domain gateways and rule engines, returning structured
observations with error isolation and follow-up guidance.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from epr_agent.domain.epr_rules import (
    CaseFormResolver,
    evaluate_assessment,
    follow_up_question,
)
from epr_agent.domain.models import DocumentRecord, EvidenceAssessment, TaskType
from epr_agent.domain.routes import RouteType
from epr_agent.domain.v4 import FactConfirmationStatus, FactSource, FactValue
from epr_agent.tools.cache import RedisExactAnswerCache, ScopedAnswerCache
from epr_agent.tools.evidence import EvidenceEvaluator, verify_citations
from epr_agent.tools.generation import EvidenceGenerationGateway, GenerationGateway
from epr_agent.tools.history import HistoryGateway, UnifiedHistoryGateway
from epr_agent.tools.retrieval import QdrantLegalRetrievalGateway, RetrievalGateway

logger = logging.getLogger(__name__)


@dataclass
class ToolDependencies:
    """Injectable dependencies for tool execution."""

    retrieval: RetrievalGateway
    evidence_evaluator: EvidenceEvaluator
    generation: GenerationGateway
    cache: ScopedAnswerCache
    history: HistoryGateway
    case_resolver: CaseFormResolver


_default_deps: ToolDependencies | None = None


def get_tool_dependencies() -> ToolDependencies:
    """Lazy initialization of production tool adapters."""
    global _default_deps
    if _default_deps is None:
        from backend.config import get_settings
        from scripts.canonical_corpus import corpus_sha256

        settings = get_settings()
        appendix_path = (
            settings.appendix_xxii_data_path
            if getattr(settings, "agent_pipeline_version", "pipeline-v3") == "pipeline-v4"
            else None
        )
        corpus_sha = corpus_sha256(
            law_path=settings.law_data_path,
            manifest_path=settings.corpus_manifest_path,
            appendix_path=appendix_path,
        )

        _default_deps = ToolDependencies(
            retrieval=QdrantLegalRetrievalGateway(),
            evidence_evaluator=EvidenceEvaluator(
                min_docs=getattr(settings, "min_legal_evidence_docs", 1),
                min_chars=getattr(settings, "min_legal_evidence_chars", 160),
            ),
            generation=EvidenceGenerationGateway(),
            cache=ScopedAnswerCache(
                RedisExactAnswerCache(),
                corpus_version=str(getattr(settings, "corpus_version", "epr-corpus-v1")),
                corpus_id=str(getattr(settings, "corpus_id", "epr")),
                corpus_sha=corpus_sha,
                embedding_profile=str(getattr(settings, "embedding_profile", "openai-text-embedding-3-small-v1")),
            ),
            history=UnifiedHistoryGateway(),
            case_resolver=CaseFormResolver(),
        )
    return _default_deps


def set_tool_dependencies(deps: ToolDependencies | None) -> None:
    """Override dependencies (used in unit/integration tests)."""
    global _default_deps
    _default_deps = deps


def _suggest_followup(query: str, assessment: EvidenceAssessment) -> str | None:
    """Suggest query revision to help the agent recover from insufficient evidence."""
    if assessment.reason == "explicit_article_not_found":
        return f"Thử bỏ số Điều cụ thể và tìm kiếm theo nội dung / từ khóa: '{query}'"
    if assessment.reason == "content_too_short":
        return f"Thử mở rộng từ khóa hoặc thêm tên văn bản (ví dụ: '{query} Nghị định 08')"
    if assessment.reason == "not_enough_docs":
        return f"Thử tìm bằng các thuật ngữ đồng nghĩa của EPR hoặc tên đối tượng liên quan."
    return None


# ══════════════════════════════════════════════════════════════════════════════
# 7 AGENT TOOL FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════


async def search_legal_provisions(
    query: str,
    required_anchors: list[str] | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """Tìm kiếm các điều khoản pháp luật trong kho văn bản pháp luật chính thức (Qdrant).

    Sử dụng khi: Cần tra cứu quy định, điều khoản, ngưỡng doanh thu, tỷ lệ đóng góp EPR.
    Không sử dụng khi: Câu hỏi xã giao (chitchat) hoặc đã có đầy đủ bằng chứng cần thiết.

    Args:
        query: Câu truy vấn pháp lý tiếng Việt cụ thể (ví dụ: 'ngưỡng doanh thu tái chế bao bì nhựa Điều 54').
        required_anchors: Danh sách Điều/Khoản cần đối chiếu bắt buộc nếu đã biết (ví dụ: ['Điều 77']).
        top_k: Số lượng văn bản trả về (1-8, mặc định 5).
    """
    deps = get_tool_dependencies()
    try:
        docs = await deps.retrieval.legal(query)
        selected = docs[: max(1, min(top_k, 8))]
        assessment = deps.evidence_evaluator.evaluate(
            query,
            selected,
            TaskType.LEGAL_LOOKUP,
            expected_articles=set(required_anchors) if required_anchors else None,
        )
        return {
            "documents": [d.to_dict() for d in selected],
            "total_found": len(docs),
            "evidence_sufficient": assessment.sufficient,
            "reason": assessment.reason,
            "suggested_followup_query": (
                _suggest_followup(query, assessment) if not assessment.sufficient else None
            ),
            "ok": True,
        }
    except Exception as exc:  # noqa: BLE001 - tools must return safe observations
        logger.warning("search_legal_provisions failed for query=%r: %s", query, exc)
        return {
            "documents": [],
            "total_found": 0,
            "evidence_sufficient": False,
            "reason": f"retrieval_error: {type(exc).__name__}",
            "error": str(exc),
            "ok": False,
        }


async def search_web_official(query: str) -> dict[str, Any]:
    """Tìm kiếm thông tin trên các cổng thông tin pháp luật chính thức (vbpl.vn, vanban.chinhphu.vn).

    Sử dụng khi: Người dùng yêu cầu tra cứu nguồn web công khai hoặc khi kho văn bản nội bộ chưa cập nhật.
    Lưu ý: Chỉ tìm kiếm trên các tên miền cơ quan nhà nước được cấp phép.

    Args:
        query: Câu truy vấn tìm kiếm tiếng Việt.
    """
    deps = get_tool_dependencies()
    try:
        answer, docs = await deps.generation.web(query)
        assessment = deps.evidence_evaluator.evaluate(query, docs, TaskType.LEGAL_LOOKUP)
        return {
            "answer_summary": answer,
            "documents": [d.to_dict() for d in docs],
            "total_found": len(docs),
            "evidence_sufficient": assessment.sufficient,
            "reason": assessment.reason,
            "ok": True,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("search_web_official failed for query=%r: %s", query, exc)
        return {
            "answer_summary": "",
            "documents": [],
            "total_found": 0,
            "evidence_sufficient": False,
            "reason": f"web_search_error: {type(exc).__name__}",
            "error": str(exc),
            "ok": False,
        }


async def lookup_answer_cache(query: str, route: str = "legal_lookup") -> dict[str, Any]:
    """Tra cứu bộ nhớ đệm (Redis Cache) xem câu hỏi pháp lý tương tự đã có câu trả lời được kiểm chứng chưa.

    Sử dụng khi: Bắt đầu xử lý câu hỏi tra cứu pháp luật (legal_lookup hoặc legal_explain_compare).
    Không dùng khi: Đánh giá case cụ thể (case_assessment) do phụ thuộc vào tình huống người dùng.

    Args:
        query: Câu hỏi cần tra cứu cache.
        route: Phân loại câu hỏi ('legal_lookup' hoặc 'legal_explain_compare').
    """
    deps = get_tool_dependencies()
    try:
        cached, key = await deps.cache.lookup(TaskType.LEGAL_LOOKUP, query, route=route)
        if cached is not None:
            docs = [DocumentRecord.from_dict(d) for d in cached.evidence]
            valid, _, reason = verify_citations(cached.answer, docs, TaskType.LEGAL_LOOKUP)
            if valid:
                return {
                    "hit": True,
                    "answer": cached.answer,
                    "evidence": list(cached.evidence),
                    "citations": list(cached.citations),
                    "source": cached.source,
                    "cache_key": key,
                    "ok": True,
                }
        return {"hit": False, "answer": None, "cache_key": key, "ok": True}
    except Exception as exc:  # noqa: BLE001
        logger.debug("lookup_answer_cache failed: %s", exc)
        return {"hit": False, "answer": None, "error": str(exc), "ok": False}


async def evaluate_epr_obligation(facts: dict[str, str]) -> dict[str, Any]:
    """Áp dụng bộ quy tắc EPR (EPR Rule Pack) để đánh giá nghĩa vụ pháp lý từ các dữ kiện đã thu thập.

    Sử dụng khi: Đã có đủ các thông tin tình huống (vai trò doanh nghiệp, đối tượng bao bì/sản phẩm, thị trường, doanh thu).

    Args:
        facts: Từ điển các sự kiện đã cung cấp, ví dụ:
               {'business_role': 'manufacturer', 'object_kind': 'commercial_packaging',
                'product_group': 'bao_bi', 'market_placement': 'vietnam_market', 'annual_revenue_vnd': '40000000000'}
    """
    deps = get_tool_dependencies()
    try:
        typed_facts: dict[str, FactValue] = {
            k: FactValue(
                value=str(v),
                source=FactSource.USER_TURN,
                confirmation_status=FactConfirmationStatus.USER_CONFIRMED,
                verified=True,
            )
            for k, v in (facts or {}).items()
            if str(v).strip()
        }
        assessment_result = evaluate_assessment(typed_facts, evidence_ids={})
        return {
            "status": assessment_result.status.value,
            "conclusion": assessment_result.conclusion,
            "reasons": [r.model_dump(mode="json") for r in assessment_result.reasons],
            "missing_facts": assessment_result.missing_facts,
            "assumptions": assessment_result.assumptions,
            "next_steps": assessment_result.next_steps,
            "rule_id": assessment_result.rule_id,
            "ok": True,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("evaluate_epr_obligation failed: %s", exc)
        return {"status": "error", "error": str(exc), "ok": False}


async def get_case_form_fields(
    task_type: str = "assess_epr_obligation",
    known_facts: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Lấy danh sách các trường thông tin cần thiết và xác định thông tin nào còn thiếu.

    Sử dụng khi: Bắt đầu xử lý tình huống đánh giá nghĩa vụ (case_assessment) hoặc lập checklist tuân thủ.

    Args:
        task_type: Loại tác vụ ('assess_epr_obligation' hoặc 'build_compliance_checklist').
        known_facts: Các thông tin người dùng đã cung cấp sẵn.
    """
    deps = get_tool_dependencies()
    try:
        form_state = deps.case_resolver.from_strings(
            task_type=task_type,
            facts=None,
            updates=known_facts or {},
        )
        return {
            "status": form_state.status,
            "missing_facts": list(form_state.missing_facts),
            "completed_count": form_state.completed_count,
            "required_count": form_state.required_count,
            "fields": [f.model_dump(mode="json") for f in form_state.fields],
            "submission_blocked_reason": form_state.submission_blocked_reason,
            "suggested_follow_up": follow_up_question(list(form_state.missing_facts)),
            "ok": True,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_case_form_fields failed: %s", exc)
        return {"status": "error", "missing_facts": [], "fields": [], "error": str(exc), "ok": False}


async def load_conversation_context(user_id: str, conversation_id: str) -> dict[str, Any]:
    """Tải lịch sử hội thoại và tình huống vụ việc đang xử lý dở dang (nếu có).

    Args:
        user_id: Mã định danh người dùng.
        conversation_id: Mã phiên hội thoại.
    """
    deps = get_tool_dependencies()
    try:
        snapshot = await deps.history.load(user_id, conversation_id, max_messages=6)
        return {
            "history_messages": snapshot.history,
            "history_summary": snapshot.summary,
            "active_case": snapshot.active_case,
            "has_active_case": bool(snapshot.active_case),
            "ok": True,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("load_conversation_context failed: %s", exc)
        return {"history_messages": [], "history_summary": "", "active_case": None, "error": str(exc), "ok": False}


async def ask_user_for_clarification(
    question: str,
    missing_fields: list[str] | None = None,
) -> dict[str, Any]:
    """Tạo câu hỏi yêu cầu người dùng bổ sung thông tin còn thiếu.

    Sử dụng khi: Cần người dùng làm rõ hoặc cung cấp thêm dữ kiện để tiếp tục đánh giá.
    LƯU Ý: Sau khi gọi công cụ này, Agent sẽ kết thúc lượt và chờ người dùng phản hồi.

    Args:
        question: Câu hỏi hướng dẫn người dùng bổ sung thông tin bằng tiếng Việt.
        missing_fields: Danh sách các trường thông tin cần làm rõ (ví dụ: ['material', 'annual_revenue_vnd']).
    """
    return {
        "action": "ask_user",
        "question": question,
        "missing_fields": missing_fields or [],
        "awaiting_user_input": True,
        "ok": True,
    }


ALL_AGENT_TOOLS = [
    search_legal_provisions,
    search_web_official,
    lookup_answer_cache,
    evaluate_epr_obligation,
    get_case_form_fields,
    load_conversation_context,
    ask_user_for_clarification,
]
