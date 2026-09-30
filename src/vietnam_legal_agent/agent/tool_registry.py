"""Tool registry for the autonomous Vietnamese legal agent.

Defines the tools available for the LLM to call during its cognitive loop.
Each tool wraps existing domain gateways and rule engines, returning structured
observations with error isolation and follow-up guidance.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any

from vietnam_legal_agent.domain.legal import parse_required_anchors
from vietnam_legal_agent.domain.models import DocumentRecord, EvidenceAssessment, TaskType
from vietnam_legal_agent.domain.v4 import RetrievalRequest
from vietnam_legal_agent.tools.cache import RedisExactAnswerCache, ScopedAnswerCache
from vietnam_legal_agent.tools.evidence import EvidenceEvaluator, verify_citations
from vietnam_legal_agent.tools.generation import EvidenceGenerationGateway, GenerationGateway
from vietnam_legal_agent.tools.history import HistoryGateway, UnifiedHistoryGateway
from vietnam_legal_agent.tools.legal_readiness import LegalReadinessProvider
from vietnam_legal_agent.tools.retrieval import (
    RequiredAnchorParseError,
    RetrievalGateway,
    UniversalLegalRetrievalGateway,
)

logger = logging.getLogger(__name__)


@dataclass
class ToolDependencies:
    """Injectable dependencies for tool execution."""

    retrieval: RetrievalGateway
    evidence_evaluator: EvidenceEvaluator
    generation: GenerationGateway
    cache: ScopedAnswerCache
    history: HistoryGateway
    legal_readiness: LegalReadinessProvider | None = None


_default_deps: ToolDependencies | None = None


def get_tool_dependencies() -> ToolDependencies:
    """Lazy initialization of production tool adapters."""
    global _default_deps
    if _default_deps is None:
        from vietnam_legal_agent.config import get_settings

        settings = get_settings()
        cache_corpus_id = "vietnamese_law"
        cache_corpus_version = str(getattr(settings, "corpus_version", "vietnamese-law-v1"))
        manifest_path = settings.universal_corpus_manifest_path
        try:
            manifest_bytes = manifest_path.read_bytes()
            manifest = json.loads(manifest_bytes)
            corpus_sha = hashlib.sha256(manifest_bytes).hexdigest()
            cache_corpus_id = str(manifest.get("corpus_id") or cache_corpus_id)
            cache_corpus_version = str(manifest.get("corpus_version") or cache_corpus_version)
        except (OSError, ValueError):
            corpus_sha = ""
        legal_readiness = None

        _default_deps = ToolDependencies(
            retrieval=UniversalLegalRetrievalGateway(),
            evidence_evaluator=EvidenceEvaluator(
                min_docs=getattr(settings, "min_legal_evidence_docs", 1),
                min_chars=getattr(settings, "min_legal_evidence_chars", 160),
            ),
            generation=EvidenceGenerationGateway(),
            cache=ScopedAnswerCache(
                RedisExactAnswerCache(),
                corpus_version=cache_corpus_version,
                corpus_id=cache_corpus_id,
                corpus_sha=corpus_sha,
                embedding_profile=str(getattr(settings, "embedding_profile", "openai-text-embedding-3-small-v1")),
                legal_readiness_sha=legal_readiness.manifest_sha256 if legal_readiness else "",
            ),
            history=UnifiedHistoryGateway(),
            legal_readiness=legal_readiness,
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
        return f"Thử diễn đạt cụ thể hơn hoặc thêm tên văn bản pháp luật (ví dụ: '{query} Bộ luật Lao động')"
    if assessment.reason == "not_enough_docs":
        return "Thử tìm bằng thuật ngữ pháp lý cụ thể hơn hoặc tên đối tượng liên quan."
    return None


# ══════════════════════════════════════════════════════════════════════════════
# 9 AGENT TOOL FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════


async def search_legal_provisions(
    query: str,
    required_anchors: list[str] | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """Tìm kiếm điều khoản trong kho văn bản pháp luật đa lĩnh vực.

    Sử dụng khi: Cần tra cứu quy định, điều khoản, ngưỡng, nghĩa vụ, hoặc chế tài pháp lý.
    Không sử dụng khi: Câu hỏi xã giao (chitchat) hoặc đã có đầy đủ bằng chứng cần thiết.

    Args:
        query: Câu truy vấn pháp lý tiếng Việt cụ thể về nội dung người dùng cần tra cứu.
        required_anchors: Danh sách Điều/Khoản cần đối chiếu bắt buộc nếu người dùng nêu rõ (ví dụ: ['Điều 12']).
        top_k: Số lượng văn bản trả về (1-8, mặc định 5).
    """
    deps = get_tool_dependencies()
    raw_required_anchors = list(required_anchors or [])
    request = RetrievalRequest(
        route="legal_lookup",
        issue_id="agent_legal_lookup",
        query=query,
        required_anchors=raw_required_anchors,
        top_k=max(1, min(top_k, 20)),
    )
    try:
        parsed_anchors, invalid_anchors = parse_required_anchors(raw_required_anchors)
        if invalid_anchors:
            extra_terms = " ".join(a for a in invalid_anchors if a.lower() not in query.lower())
            if extra_terms:
                query = f"{query} {extra_terms}".strip()
                request.query = query
        request.required_anchors = [a.article or a.key() for a in parsed_anchors]
        docs = await deps.retrieval.legal(request)
        selected = docs[: max(1, min(top_k, 8))]
        assessment = deps.evidence_evaluator.evaluate(
            query,
            selected,
            TaskType.LEGAL_LOOKUP,
            expected_articles={anchor.article for anchor in parsed_anchors if anchor.article} or None,
            expected_anchors=parsed_anchors or None,
        )
        return {
            "documents": [d.to_dict() for d in selected],
            "total_found": len(docs),
            "required_anchors": raw_required_anchors,
            "evidence_sufficient": assessment.sufficient,
            "reason": assessment.reason,
            "suggested_followup_query": (
                _suggest_followup(query, assessment) if not assessment.sufficient else None
            ),
            "ok": True,
        }
    except Exception as exc:  # noqa: BLE001 - tools must return safe observations
        logger.warning("search_legal_provisions failed for query=%r: %s", query, exc)
        reason = (
            "required_anchor_parse_failed"
            if isinstance(exc, RequiredAnchorParseError)
            else f"retrieval_error: {type(exc).__name__}"
        )
        return {
            "documents": [],
            "total_found": 0,
            "evidence_sufficient": False,
            "required_anchors": raw_required_anchors,
            "reason": reason,
            "error": str(exc),
            "ok": False,
        }


async def search_web_official(query: str) -> dict[str, Any]:
    """Tìm kiếm thông tin trên các cổng thông tin pháp luật chính thức (vbpl.vn, vanban.chinhphu.vn, thuvienphapluat.vn).

    Sử dụng khi: Người dùng yêu cầu tra cứu nguồn web công khai hoặc khi kho văn bản nội bộ chưa cập nhật.
    Lưu ý: Chỉ tìm kiếm trên các tên miền cơ quan nhà nước và cổng pháp lý được cấp phép.

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
        readiness = None
        readiness_provider = deps.legal_readiness
        if readiness_provider is not None:
            readiness = readiness_provider.audit()
            deps.cache.update_legal_readiness_sha(readiness.manifest_sha256)
            if not readiness.legally_ready:
                readiness_reason = (
                    "legal_readiness_invalid"
                    if readiness.status.value == "invalid"
                    else readiness.reason
                )
                return {
                    "hit": False,
                    "answer": None,
                    "cache_key": deps.cache.build_key(TaskType.LEGAL_LOOKUP, query, route=route),
                    "reason": readiness_reason,
                    "legal_readiness_status": readiness.status.value,
                    "legal_readiness_issues": list(readiness.issues),
                    "ok": True,
                }
        cached, key = await deps.cache.lookup(TaskType.LEGAL_LOOKUP, query, route=route)
        if cached is not None:
            docs = [DocumentRecord.from_dict(d) for d in cached.evidence]
            if readiness_provider is not None and readiness is not None:
                allowed, readiness_reason = readiness_provider.allows_documents(docs)
                if not allowed:
                    return {
                        "hit": False,
                        "answer": None,
                        "cache_key": key,
                        "reason": readiness_reason,
                        "legal_readiness_status": readiness.status.value,
                        "ok": True,
                    }
            valid, _, _reason = verify_citations(cached.answer, docs, TaskType.LEGAL_LOOKUP)
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


async def evaluate_legal_case(
    legal_domain: str,
    facts: dict[str, str],
) -> dict[str, Any]:
    """Deprecated: deterministic domain rules cannot establish legal evidence."""
    logger.info(
        "evaluate_legal_case called without a source-backed assessment; domain=%s facts=%d",
        legal_domain,
        len(facts or {}),
    )
    return {
        "status": "retrieval_required",
        "error": "Tra cứu nguồn pháp luật và kiểm chứng căn cứ trước khi đánh giá tình huống.",
        "ok": False,
    }


async def calculate_statutory_amounts(
    calculation_type: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    """Thực hiện các phép tính toán số liệu pháp lý chuẩn hóa theo luật định Việt Nam.

    Các loại tính toán hỗ trợ (calculation_type):
    - 'overtime_salary': Tính tiền lương làm thêm giờ (150% ngày thường, 200% chủ nhật, 300% ngày lễ/tết theo Đ.98 BLLĐ).
      Params: {'monthly_salary_vnd': float, 'hourly_wage_vnd': float, 'overtime_hours': float, 'day_type': 'weekday'|'weekend'|'holiday', 'is_night': bool}
    - 'unlawful_termination_compensation': Bồi thường sa thải trái luật theo Đ.41 BLLĐ (ít nhất 2 tháng lương + lương ngày không làm việc + bồi thường vi phạm báo trước).
      Params: {'monthly_salary_vnd': float, 'months_unworked': float, 'unnotified_days': float}
    - 'severance_allowance': Trợ cấp thôi việc theo Đ.46 BLLĐ (0.5 tháng lương/năm làm việc).
      Params: {'monthly_salary_average_6m_vnd': float, 'qualifying_working_years': float}
    - 'probation_wage_floor': Mức sàn tiền lương thử việc tối thiểu 85% theo Đ.26 BLLĐ.
      Params: {'official_salary_vnd': float, 'actual_probation_wage_vnd': float}
    - 'traffic_fine': Tra cứu khung phạt vi phạm giao thông theo NĐ 100/2019 & NĐ 123/2021 (cồn, đèn đỏ, đèn vàng).
      Params: {'vehicle_type': 'motorbike'|'car', 'violation_act': 'alcohol'|'traffic_light', 'alcohol_concentration': 'level_1'|'level_2'|'level_3'}
    - 'traffic_accident_damage_compensation': Tính tổng tiền bồi thường thiệt hại do tai nạn giao thông/xâm phạm sức khỏe & tài sản theo Điều 584, 585, 589, 590 Bộ luật Dân sự 2015.
      Params: {'medical_expenses_vnd': float, 'property_damage_vnd': float, 'lost_income_vnd': float, 'monthly_income_vnd': float, 'months_unworked': float, 'caretaker_costs_vnd': float}
    - 'household_business_tax': Tính thuế khoán hộ kinh doanh cá thể (GTGT + TNCN theo Thông tư 40/2021/TT-BTC).
      Params: {'monthly_revenue_vnd': float, 'business_sector': 'food_and_beverage'|'retail_trade'|'other_services'}
    - 'personal_income_tax': Tính thuế TNCN biểu lũy tiến 7 bậc theo Luật Thuế TNCN (giảm trừ bản thân 11tr, người phụ thuộc 4.4tr).
      Params: {'monthly_income_vnd': float, 'dependents_count': int, 'insurance_deduction_vnd': float}
    - 'late_payment_interest': Tính tiền lãi chậm trả và trần lãi suất vay 20%/năm theo Điều 468 BLDS 2015.
      Params: {'principal_vnd': float, 'overdue_days': int, 'agreed_rate_annual_percent': float}

    Args:
        calculation_type: Loại công thức cần tính toán.
        parameters: Các tham số đầu vào cho công thức.
    """
    from vietnam_legal_agent.domain.legal_rules import calculate_legal_formula

    try:
        res = calculate_legal_formula(calculation_type=calculation_type, parameters=parameters)
        if isinstance(res, dict) and res.get("ok"):
            legal_basis = str(res.get("legal_basis") or "")
            summary = str(res.get("formatted_summary") or res.get("formula") or "")
            if legal_basis:
                doc = {
                    "id": "calc_basis_1",
                    "document_id": "calc_basis_1",
                    "text": f"{legal_basis}: {summary}",
                    "content": f"{legal_basis}: {summary}",
                    "source": "legal",
                    "title": legal_basis,
                    "source_title": legal_basis,
                    "metadata": {"Source_Title": legal_basis},
                }
                res["evidence"] = [doc]
                res["documents"] = [doc]
        return res
    except Exception as exc:  # noqa: BLE001
        logger.warning("calculate_statutory_amounts failed for type=%r: %s", calculation_type, exc)
        return {"status": "error", "error": str(exc), "ok": False}


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
) -> dict[str, Any]:
    """Ask one concise natural-language follow-up when a material fact is missing."""
    return {
        "action": "ask_user",
        "status": "need_clarification",
        "question": question,
        "awaiting_user_input": True,
        "ok": True,
    }



ALL_AGENT_TOOLS = [
    search_legal_provisions,
    search_web_official,
    lookup_answer_cache,
    load_conversation_context,
    ask_user_for_clarification,
]
